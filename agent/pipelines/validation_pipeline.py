"""
Validation Pipeline

This pipeline validates responses from sub-agents (query_db, agentic_rag) before
returning to the user. It also intelligently triggers additional tool calls when needed,
such as calling RAG for business insights after data analysis.

The validation process:
1. Validates response quality and accuracy
2. Checks if additional context/insights are needed
3. Triggers follow-up tools if necessary (e.g., RAG for recommendations)
4. Returns validated response or suggests improvements
"""

import logging
import json
from typing import Dict, List, Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


def validate_response_quality(
    draft_response: str,
    user_query: str,
    source_data: Optional[Dict],
    llm
) -> Dict:
    """
    Validates the quality and accuracy of a draft response.

    Args:
        draft_response: The response to validate
        user_query: Original user question
        source_data: Data used to generate the response
        llm: Language model for validation

    Returns:
        Dict with validation results
    """
    logging.info("[Validation] Validating response quality...")

    validation_prompt = ChatPromptTemplate.from_template(
        """Validate this Bonat AI assistant response for quality.

**Question:** {user_query}
**Response:** {draft_response}
**Source Data:** {source_data}

**Check:**
1. Does the response answer the question? (Be lenient — "total visits" + a number = valid)
2. Do numbers match the source data exactly?
3. Bonat terminology: Rewards=points-based, Gifts=free from merchant, Coupons=purchased with money
4. No hallucinated data or unsupported claims?

**Return JSON only:**
{{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "issues": ["specific issues if any"],
    "feedback": "brief explanation",
    "needs_enhancement": true/false,
    "enhancement_suggestion": "what would improve this, if anything"
}}"""
    )

    chain = validation_prompt | llm | StrOutputParser()

    try:
        result = chain.invoke({
            "user_query": user_query,
            "draft_response": draft_response,
            "source_data": json.dumps(source_data, indent=2) if source_data else "No source data provided"
        })

        # Parse JSON response
        validation = json.loads(result.strip())
        logging.info(f"[Validation] Quality check result: {validation}")

        return validation

    except Exception as e:
        logging.error(f"[Validation] Quality validation failed: {e}")
        # Default to accepting response if validation fails
        return {
            "is_valid": True,
            "confidence": 0.7,
            "issues": [],
            "feedback": "Validation check encountered an error, proceeding with response",
            "needs_enhancement": False,
            "enhancement_suggestion": None
        }


def check_needs_business_insights(
    user_query: str,
    draft_response: str,
    source_tool: str,
    llm
) -> Dict:
    """
    Determines if business insights/recommendations should be added to the response.

    Currently always returns False — the Main Agent decides whether to call RAG
    based on the user's original question, not the validation tool.

    Args:
        user_query: Original user question
        draft_response: Current response from query_db
        source_tool: Which tool generated the response
        llm: Language model (unused — kept for API compatibility)

    Returns:
        Dict with decision on whether to enhance with insights
    """
    # The Main Agent orchestrates RAG calls directly — validation only checks quality.
    # No LLM call needed here.
    logging.info("[Validation] Insights check: skipped (Main Agent handles RAG decisions)")
    return {
        "needs_insights": False,
        "reason": "Main Agent handles RAG decisions directly",
        "insight_query": None
    }


def execute_validation_pipeline(
    draft_response: str,
    user_query: str,
    source_tool: str,
    source_data: Optional[Dict] = None
) -> Dict:
    """
    Execute the complete validation pipeline.

    This orchestrates:
    1. Response quality validation
    2. Business insights detection
    3. Returns validation result with signal to Main Agent

    The Main Agent will decide whether to call RAG based on the validation result.

    Args:
        draft_response: Response from a sub-agent to validate
        user_query: Original user question
        source_tool: Which tool generated the response (query_db, agentic_rag)
        source_data: Optional data used to generate response

    Returns:
        Dict with validation results and recommendation signal:
        {
            "is_valid": bool,
            "confidence": float,
            "issues": List[str],
            "needs_rag_insights": bool,
            "suggested_rag_query": str (if needs_rag_insights is True),
            "feedback": str
        }
    """
    logging.info(f"[Validation Pipeline] Starting validation for {source_tool} response")

    # Get LLM with callbacks for cost tracking
    from agent.config import get_llm
    llm = get_llm()

    # ═══════════════════════════════════════════════════════════
    # Step 1: Validate Response Quality
    # ═══════════════════════════════════════════════════════════
    quality_check = validate_response_quality(
        draft_response=draft_response,
        user_query=user_query,
        source_data=source_data,
        llm=llm
    )

    # ═══════════════════════════════════════════════════════════
    # Step 2: Check if Business Insights Are Needed
    # ═══════════════════════════════════════════════════════════
    insights_decision = check_needs_business_insights(
        user_query=user_query,
        draft_response=draft_response,
        source_tool=source_tool,
        llm=llm
    )

    # ═══════════════════════════════════════════════════════════
    # Return Validation Result with RAG Recommendation
    # ═══════════════════════════════════════════════════════════
    logging.info("[Validation Pipeline] Validation complete")

    result = {
        "is_valid": quality_check.get("is_valid", True),
        "confidence": quality_check.get("confidence", 1.0),
        "issues": quality_check.get("issues", []),
        "feedback": quality_check.get("feedback", "Response validated successfully"),
        "needs_rag_insights": insights_decision.get("needs_insights", False),
        "suggested_rag_query": insights_decision.get("insight_query", None) if insights_decision.get("needs_insights", False) else None
    }

    if result["needs_rag_insights"]:
        logging.info(f"[Validation Pipeline] Recommending RAG call with query: {result['suggested_rag_query']}")

    return result
