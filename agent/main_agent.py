"""
Main Agent - The Orchestrator

This is the intelligent agent that coordinates all tools and handles user interactions.
It decides when to use tools (query_db, agentic_rag, validate) and when to respond directly.
"""

import asyncio
import logging
import os
import re
import traceback
from typing import List, Optional
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import BaseMessage
from langchain_core.callbacks import BaseCallbackHandler

from agent.tools import query_db, agentic_rag, validate, respond_directly

# ═══════════════════════════════════════════════════════════════════════════════
# Load modular rule files from prompts/ directory
# ═══════════════════════════════════════════════════════════════════════════════
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")


def _load_rule(filename: str) -> str:
    """Load a rule file from prompts/ directory. Returns empty string if not found."""
    path = os.path.join(_PROMPTS_DIR, filename)
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        logging.warning(f"[Main Agent] Rule file not found: {path}")
        return ""


def _has_arabic(text: str) -> bool:
    """Detect if text contains Arabic characters."""
    return bool(re.search(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]', text))


def create_main_agent(merchant_id: str, entity_context: dict = None, past_insights: list = None, user_query: str = None, language: str = "ar") -> AgentExecutor:
    """
    Creates the Main Agent with tool-calling capabilities.

    The Main Agent is the orchestrator that:
    - Receives user queries
    - Decides which tools to use (if any)
    - Maintains conversation context
    - Synthesizes responses from tools
    - Ensures merchant data isolation

    Args:
        merchant_id: The merchant's unique identifier for data isolation
        entity_context: Optional entity context from conversation history for reference resolution
        past_insights: Optional list of relevant past insights to surface
        user_query: Optional current user query — used to detect Arabic and inject dictionary

    Returns:
        AgentExecutor configured with tools and ready to handle queries
    """
    logging.info(f"[Main Agent] Creating agent for merchant: {merchant_id}")

    # ═══════════════════════════════════════════════════════════
    # Initialize LLM with Tool Calling
    # ═══════════════════════════════════════════════════════════
    from agent.config import get_llm
    llm = get_llm()

    # ═══════════════════════════════════════════════════════════
    # Define Available Tools
    # ═══════════════════════════════════════════════════════════
    tools = [query_db, agentic_rag, validate, respond_directly]

    # ═══════════════════════════════════════════════════════════
    # Create Agent Prompt
    # ═══════════════════════════════════════════════════════════
    from agent.config import get_merchant_now
    _now = get_merchant_now()
    current_date = _now.strftime("%Y-%m-%d")
    current_day_name = _now.strftime("%A")

    # Load modular rule files
    tool_usage_rules = _load_rule("tool_usage.md")
    routing_rules = _load_rule("routing_rules.md")
    data_boundary_rules = _load_rule("data_boundaries.md")
    anti_hallucination_rules = _load_rule("anti_hallucination.md")
    error_handling_rules = _load_rule("error_handling.md")
    soul_rules = _load_rule("soul.md").replace("{merchant_id}", merchant_id)

    # Build language instruction based on language parameter
    if language == "ar":
        language_instruction = "Respond in Saudi Arabic (عامية سعودية). Use natural Saudi expressions. Numbers + currency in Arabic context."
    else:
        language_instruction = "Respond in English. Use SAR for currency."

    prompt = ChatPromptTemplate.from_messages([
        ("system", """{soul}

<language>
{language_instruction}
</language>

<date_context>
Today: {current_date} ({current_day_name}).
Date synonyms (the system resolves dates deterministically — pass the user's words directly):
- "last 7 days" = "past week" = 7 days back from today
- "last week" = "previous week" = previous full Mon–Sun
- "last month" = full previous calendar month
- "this week" = Monday of current week to today
- Arabic date expressions — CRITICAL: pass as "last week", "last month", etc. DO NOT rephrase as "last 7 days":
  - "آخر أسبوع" / "الأسبوع الماضي" = "last week" (Mon–Sun calendar week, NOT last 7 days)
  - "آخر شهر" / "الشهر الماضي" = "last month"
  - "هذا الأسبوع" = "this week"
  - "اليوم" = "today"
  - "أمس" / "البارحة" = "yesterday"
  - "آخر ٧ أيام" = "last 7 days"
</date_context>

<tools>
You have 4 tools. Call at least one tool on every turn.

Available intent categories for query_db:
{intent_descriptions}

{tool_usage_rules}
</tools>

{routing_rules}

<platform>
Bonat: Saudi loyalty/CX platform. Merchants manage rewards, track segments, run campaigns.
{terminology}
{arabic_dictionary}
System: Dashboard + Mobile App + POS Tablet + Foodics/Retem/Rawa/Dojo integrations.
</platform>

<workflow>
1. Classify: data question → query_db, knowledge question → agentic_rag, greeting → respond_directly.
2. For data: set intent_category, call query_db, then format the response.
3. Use validate only if uncertain about data quality — optional, at most once.
4. Format: warm, conversational, concise. Use tables or bullet points for data. Currency in SAR.
</workflow>

{error_handling_rules}

{data_boundary_rules}

{anti_hallucination_rules}

<context>
{entity_context}
Reuse resolved dates from context for follow-ups unless user specifies new dates.
</context>

{past_insights}
"""),
        MessagesPlaceholder(variable_name="chat_history", optional=True),
        ("user", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    # Format entity context for prompt injection
    from agent.entity_tracker import format_entity_context
    entity_context_str = format_entity_context(entity_context or {})

    # Format past insights for prompt injection
    from agent.insights_memory import format_insights_for_prompt
    past_insights_str = format_insights_for_prompt(past_insights or [])

    # Generate dynamic prompt sections from YAML semantic model
    from agent.semantic_model import get_semantic_model
    _model = get_semantic_model()
    intent_descriptions_str = _model.generate_intent_descriptions()
    terminology_str = _model.generate_terminology_prompt()

    # Inject Arabic dictionary when language is Arabic or when Arabic text is detected
    arabic_dictionary_str = ""
    if language == "ar" or (user_query and _has_arabic(user_query)):
        arabic_dictionary_str = _model.generate_arabic_dictionary_prompt()
        logging.info("[Main Agent] Arabic language/text — injecting Arabic dictionary into prompt")

    # Bind all dynamic values to the prompt
    prompt = prompt.partial(
        soul=soul_rules,
        language_instruction=language_instruction,
        current_date=current_date,
        current_day_name=current_day_name,
        entity_context=entity_context_str,
        past_insights=past_insights_str,
        intent_descriptions=intent_descriptions_str,
        terminology=terminology_str,
        arabic_dictionary=arabic_dictionary_str,
        tool_usage_rules=tool_usage_rules,
        routing_rules=routing_rules,
        data_boundary_rules=data_boundary_rules,
        anti_hallucination_rules=anti_hallucination_rules,
        error_handling_rules=error_handling_rules,
    )

    # ═══════════════════════════════════════════════════════════
    # Create Agent
    # ═══════════════════════════════════════════════════════════
    agent = create_tool_calling_agent(
        llm=llm,
        tools=tools,
        prompt=prompt
    )

    # ═══════════════════════════════════════════════════════════
    # Create Agent Executor
    # ═══════════════════════════════════════════════════════════
    def _handle_error(error: Exception) -> str:
        """Custom error handler that logs the error"""
        logging.error(f"[Main Agent] Parsing error occurred: {error}", exc_info=True)
        return str(error)

    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=os.getenv("ENVIRONMENT", "production") == "development",
        max_iterations=5,  # Fail fast — prevents timeout loops
        max_execution_time=120,  # 2 minutes is enough for GPT-4.1-mini
        handle_parsing_errors=_handle_error,  # Log parsing errors instead of silently handling
        return_intermediate_steps=False,  # Don't return tool call details to user
    )

    logging.info(f"[Main Agent] Agent created successfully for merchant: {merchant_id}")

    return agent_executor


def invoke_main_agent(
    agent_executor: AgentExecutor,
    user_query: str,
    merchant_id: str,
    chat_history: Optional[List[BaseMessage]] = None
) -> str:
    """
    Invokes the Main Agent with a user query.

    Args:
        agent_executor: The configured AgentExecutor
        user_query: The user's question or message
        merchant_id: The merchant's unique identifier
        chat_history: Optional list of previous messages for context

    Returns:
        The agent's response as a string
    """
    logging.info(f"[Main Agent] Invoking agent for query: {user_query}")

    try:
        result = agent_executor.invoke({
            "input": user_query,
            "chat_history": chat_history or [],
        })

        logging.info(f"[Main Agent] Agent execution completed. Result type: {type(result)}")
        logging.info(f"[Main Agent] Result keys: {result.keys() if isinstance(result, dict) else 'Not a dict'}")

        response = result.get("output", "I apologize, I couldn't generate a response.")
        logging.info(f"[Main Agent] Response type: {type(response)}, length: {len(str(response))}")
        logging.info(f"[Main Agent] Response generated: {response[:100]}...")

        return response

    except Exception as e:
        logging.error(f"[Main Agent] Error during invocation: {e}")
        logging.error(f"[Main Agent] Full traceback:\n{traceback.format_exc()}")
        return "I apologize, I encountered an unexpected error. Please try again or rephrase your question."


async def stream_main_agent(
    agent_executor: AgentExecutor,
    user_query: str,
    merchant_id: str,
    chat_history: Optional[List[BaseMessage]] = None,
    callbacks: Optional[List[BaseCallbackHandler]] = None
):
    """
    Streams tokens from the Main Agent in real-time using Server-Sent Events.

    This function uses LangChain's astream_events API to capture token-by-token
    output from the LLM as it generates responses. It filters out intermediate
    tool calls and only streams the final agent response.

    Args:
        agent_executor: The configured AgentExecutor
        user_query: The user's question or message
        merchant_id: The merchant's unique identifier
        chat_history: Optional list of previous messages for context
        callbacks: Optional list of LangChain callbacks for tracking (e.g., CostTrackingCallback)

    Yields:
        dict: Event objects with structure:
            - {"type": "token", "content": "..."} for each token
            - {"type": "tool_start", "tool": "query_db", "status": "..."} for tool notifications
            - {"type": "error", "content": "..."} for errors
            - {"type": "done", "full_response": "...", "cost_data": {...}} when complete
    """
    logging.info(f"[Main Agent Stream] Starting stream for query: {user_query}")

    full_response = []  # Accumulate full response for saving to DB later
    queried_table = None  # Track which table was queried (for suggestions)

    try:
        # Track which tools are being called for status updates
        # Use counter instead of set to handle parallel calls of same tool
        active_tool_count = 0
        streaming_started = False  # Track when we start streaming final response
        tools_ever_called = False  # Track if any tools have EVER been called
        tools_all_completed = False  # Track when all tools finish (after being called)

        # Build config with callbacks for cost tracking
        stream_config = {"callbacks": callbacks} if callbacks else {}

        async for event in agent_executor.astream_events(
            {
                "input": user_query,
                "chat_history": chat_history or [],
            },
            version="v1",  # Use v1 for compatibility
            config=stream_config
        ):
            event_type = event.get("event")

            # ═══════════════════════════════════════════════════════════
            # Tool Start Events - Notify user what's happening
            # ═══════════════════════════════════════════════════════════
            if event_type == "on_tool_start":
                tool_name = event.get("name", "unknown")
                active_tool_count += 1
                tools_ever_called = True  # Mark that at least one tool was used
                tools_all_completed = False  # Reset - new tool started, not all completed anymore

                # Send detailed progress updates with descriptions
                progress_messages = {
                    "query_db": {
                        "icon": "fa-database",
                        "title": "Analyzing Data",
                        "description": "Querying your database and processing metrics"
                    },
                    "agentic_rag": {
                        "icon": "fa-book-open",
                        "title": "Searching Knowledge",
                        "description": "Looking up best practices and recommendations"
                    },
                    "validate": {
                        "icon": "fa-shield-check",
                        "title": "Validating Response",
                        "description": "Ensuring accuracy and completeness"
                    },
                    "respond_directly": {
                        "icon": "fa-comment",
                        "title": "Responding",
                        "description": "Preparing your response"
                    }
                }

                progress_data = progress_messages.get(tool_name, {
                    "icon": "fa-cog",
                    "title": f"Running {tool_name}",
                    "description": "Processing your request"
                })

                logging.info(f"[Main Agent Stream] Tool started: {tool_name}")

                yield {
                    "type": "tool_start",
                    "tool": tool_name,
                    "icon": progress_data["icon"],
                    "title": progress_data["title"],
                    "description": progress_data["description"]
                }

            # ═══════════════════════════════════════════════════════════
            # Tool End Events - Tool completed
            # ═══════════════════════════════════════════════════════════
            elif event_type == "on_tool_end":
                tool_name = event.get("name", "unknown")
                active_tool_count -= 1
                logging.info(f"[Main Agent Stream] Tool completed: {tool_name} (active: {active_tool_count})")

                # Extract table name from query_db output for suggestions
                if tool_name == "query_db":
                    tool_output = event.get("data", {}).get("output", "")
                    if isinstance(tool_output, str) and "Table:" in tool_output:
                        # Parse "Table: TableName" from the output
                        table_match = re.search(r"Table:\s*(\w+)", tool_output)
                        if table_match:
                            queried_table = table_match.group(1)
                            logging.info(f"[Main Agent Stream] Captured queried table: {queried_table}")

                # Mark that all tools have completed (tools were called, now none active)
                if tools_ever_called and active_tool_count == 0:
                    tools_all_completed = True
                    logging.info(f"[Main Agent Stream] All tools completed - ready to stream final response")

                # Send completion event
                yield {
                    "type": "tool_end",
                    "tool": tool_name
                }

            # ═══════════════════════════════════════════════════════════
            # LLM Stream Events - The actual tokens we want to stream
            # ═══════════════════════════════════════════════════════════
            elif event_type == "on_chat_model_stream":
                # CRITICAL: Only stream tokens from the FINAL agent response
                # Ignore LLM calls made by tools (SQL generation, table selection, etc.)

                # Strategy: Only stream AFTER tools have been called AND all completed
                # This prevents streaming the agent's initial "thinking" before tools run
                # The agent must call tools first, then we stream the final synthesis
                if tools_all_completed or not tools_ever_called:
                    # Extract the token from the chunk
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content"):
                        token = chunk.content

                        # Filter out empty tokens
                        if token:
                            # Mark that streaming has started (first token of final response)
                            if not streaming_started:
                                streaming_started = True
                                logging.info(f"[Main Agent Stream] Started streaming final response")

                                # Send "Generating Response" event
                                yield {
                                    "type": "generating_start",
                                    "icon": "fa-sparkles",
                                    "title": "Generating Response",
                                    "description": "Synthesizing your answer"
                                }

                            full_response.append(token)

                            yield {
                                "type": "token",
                                "content": token
                            }

                            # Add delay for better readability (30ms per token)
                            await asyncio.sleep(0.03)

        # ═══════════════════════════════════════════════════════════
        # Stream Complete - Send final event with cost data
        # ═══════════════════════════════════════════════════════════
        complete_response = "".join(full_response)
        logging.info(f"[Main Agent Stream] Stream completed. Total length: {len(complete_response)}")

        # Extract cost data from callbacks if CostTrackingCallback is present
        cost_data = None
        if callbacks:
            for callback in callbacks:
                # Check if this callback has the get_cost_summary method
                if hasattr(callback, 'get_cost_summary'):
                    cost_data = callback.get_cost_summary()
                    logging.info(
                        f"[Main Agent Stream] Cost tracking: tokens={cost_data.get('total_tokens', 0)}, "
                        f"cost=${cost_data.get('cost_usd', 0):.6f}"
                    )
                    break

        yield {
            "type": "done",
            "full_response": complete_response,
            "queried_table": queried_table,  # For contextual suggestions
            "cost_data": cost_data  # Cost tracking data (None if no callback)
        }

    except Exception as e:
        logging.error(f"[Main Agent Stream] Error during streaming: {e}")
        logging.error(f"[Main Agent Stream] Full traceback:\n{traceback.format_exc()}")

        yield {
            "type": "error",
            "content": "I apologize, I encountered an unexpected error. Please try again or rephrase your question."
        }
