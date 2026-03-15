"""
Bonat Agent Tools

This module defines the specialized tools available to the Main Agent.
Each tool encapsulates complex functionality behind a simple interface.
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Dict, Literal, Optional, Union
import logging


# ═══════════════════════════════════════════════════════════════════════════════
# Structured Tool Input — Constrained intent_category prevents misrouting
# ═══════════════════════════════════════════════════════════════════════════════

# ── Build dynamic intent_category Literal from YAML semantic model ──
from agent.semantic_model import get_semantic_model as _get_sm
_model = _get_sm()
_categories = _model.get_intent_categories()
_IntentLiteral = Literal[tuple(_categories)]  # type: ignore[valid-type]
_intent_desc = _model.generate_intent_descriptions()


class QueryDBInput(BaseModel):
    """Input schema for query_db with structured routing via intent_category."""
    user_question: str = Field(description="The user's question about their business data")
    merchant_id: Union[str, int] = Field(description="The merchant's unique identifier (automatically provided)")
    intent_category: Optional[_IntentLiteral] = Field(  # type: ignore[valid-type]
        default=None,
        description=(
            "Data category to route the query to the correct table. ALWAYS set this. Options:\n"
            + _intent_desc
        )
    )


@tool(args_schema=QueryDBInput)
def query_db(user_question: str, merchant_id: Union[str, int], intent_category: Optional[str] = None) -> str:
    """Query the merchant's business database. Call this for any question about revenue, visits, customers, segments, loyalty, orders, campaigns, or payments — including Arabic questions."""
    import time
    start_time = time.time()
    merchant_id = str(merchant_id)  # Ensure string (GPT-4.1 may pass int)
    logging.info(f"[query_db] ⏱️ START (t=0.00s) - Question: {user_question[:100]}..., merchant: {merchant_id}, intent: {intent_category}")

    from agent.pipelines.data_pipeline import execute_data_pipeline

    try:
        result = execute_data_pipeline(
            user_question=user_question,
            merchant_id=merchant_id,
            history=None,
            intent_category=intent_category,
        )

        elapsed = time.time() - start_time
        if result["success"]:
            logging.info(f"[query_db] ⏱️ END (t={elapsed:.2f}s) - SUCCESS - Question: {user_question[:100]}...")
            return result["response"]
        else:
            # Return error message
            error = result.get("error", "Unknown error")
            logging.error(f"[query_db] ⏱️ END (t={elapsed:.2f}s) - FAILED - {error}")
            return f"I encountered an issue retrieving that data: {result['response']}"

    except Exception as e:
        elapsed = time.time() - start_time
        logging.error(f"[query_db] ⏱️ END (t={elapsed:.2f}s) - ERROR - {e}", exc_info=True)
        return "I'm sorry, I encountered an unexpected error while processing your request. Please try again."


@tool
def agentic_rag(question: str, merchant_context: Optional[Dict] = None) -> str:
    """Search Bonat knowledge base for feature guides, best practices, and troubleshooting. Not for business data — use query_db for that."""
    logging.info(f"[agentic_rag] Called with question: {question}")

    from agent.pipelines.rag_pipeline import execute_agentic_rag

    try:
        answer = execute_agentic_rag(
            question=question,
            merchant_context=merchant_context,
            max_retries=2
        )
        return answer

    except Exception as e:
        logging.error(f"[agentic_rag] Error: {e}", exc_info=True)
        return "I'm sorry, I encountered an error accessing the knowledge base. Please try rephrasing your question or contact support."


@tool
def validate(
    draft_response: str,
    user_query: str,
    source_tool: str,
    source_data: Optional[str] = None
) -> str:
    """Quality check after query_db returns data. Returns VALIDATION PASSED, insights needed, or VALIDATION FAILED. If insights needed, call agentic_rag with the suggested query and combine results."""
    logging.info(f"[validate] Validating {source_tool} response for: {user_query}")

    from agent.pipelines.validation_pipeline import execute_validation_pipeline

    try:
        # Parse source_data if provided
        source_data_dict = None
        if source_data:
            try:
                import json
                source_data_dict = json.loads(source_data)
            except (json.JSONDecodeError, ValueError, TypeError):
                logging.warning("[validate] Could not parse source_data as JSON")

        # Execute validation pipeline
        result = execute_validation_pipeline(
            draft_response=draft_response,
            user_query=user_query,
            source_tool=source_tool,
            source_data=source_data_dict
        )

        # Format response for Main Agent
        if not result["is_valid"] or result["confidence"] < 0.6:
            # Validation failed
            logging.warning(f"[validate] Validation failed: {result['feedback']}")
            return f"""VALIDATION FAILED

Issues found: {', '.join(result['issues'])}
Confidence: {result['confidence']}
Feedback: {result['feedback']}

ACTION: The response has quality issues. Add a disclaimer or ask the user to rephrase."""

        elif result["needs_rag_insights"]:
            # Validation passed BUT insights are needed
            logging.info(f"[validate] Validation passed, but RAG insights recommended")
            return f"""VALIDATION PASSED - but insights needed

The response is accurate, but would benefit from business insights.

ACTION REQUIRED:
1. Call agentic_rag with this query: "{result['suggested_rag_query']}"
2. Combine the data response with the RAG insights
3. Return the combined response to the user

Data response to include:
{draft_response}"""

        else:
            # Validation passed, no insights needed
            logging.info("[validate] Validation passed, response is ready")
            return f"""VALIDATION PASSED

The response is accurate and complete. No additional insights needed.

ACTION: Return the original response to the user as-is."""

    except Exception as e:
        logging.error(f"[validate] Validation failed with error: {e}", exc_info=True)
        return f"""VALIDATION ERROR

An error occurred during validation. Proceed with caution.

ACTION: Return the original response with a disclaimer, or ask the user to rephrase."""


@tool
def respond_directly(message: str) -> str:
    """Respond to greetings, thanks, and social messages. Pass the full response text as the message parameter."""
    return message


# Export all tools
__all__ = ["query_db", "agentic_rag", "validate", "respond_directly"]
