"""
Contextual Follow-up Suggestions Module

Generates relevant follow-up questions using LLM based on:
- The table schema that was queried
- The user's original question
- The data that was returned

This ensures suggestions are always answerable by the available data.
"""

import logging
from typing import List, Optional

from agent.config import get_llm, mysql_schemas

logger = logging.getLogger(__name__)


def get_follow_up_suggestions(
    user_query: str,
    table_name: Optional[str] = None,
    query_result: Optional[str] = None,
    num_suggestions: int = 3
) -> List[str]:
    """
    Generates contextual follow-up suggestions using LLM.

    The LLM uses the actual table schema to ensure all suggestions
    are answerable queries that won't fail.

    Args:
        user_query: The user's original question
        table_name: The table that was queried
        query_result: The data returned (optional, for more context)
        num_suggestions: Number of suggestions to return (default: 3)

    Returns:
        List of follow-up question suggestions
    """
    try:
        # Get the schema for the queried table
        table_schema = ""
        if table_name and table_name in mysql_schemas:
            table_schema = mysql_schemas[table_name]

        # Get related table schemas for cross-table suggestions
        related_schemas = _get_related_schemas(table_name)

        prompt = f"""Generate {num_suggestions} follow-up questions a merchant might ask next. SHORT (max 8 words each) — these are clickable chips.

**Asked:** {user_query}
**Table used:** {table_name or "Unknown"}
**Schema:** {table_schema}
**Other tables:** {related_schemas}

**Rules:** Answerable from tables above. No SQL terms. Mix same-topic depth + cross-topic. Don't repeat the question.
**Examples:** "Compare to last month" · "Show by branch" · "Which day performed best?"

Return ONLY {num_suggestions} suggestions, one per line, no bullets or numbers."""

        response = get_llm().invoke(prompt)
        suggestions_text = response.content.strip()

        # Parse the response into a list
        suggestions = [
            line.strip().strip('•-"\'')
            for line in suggestions_text.split('\n')
            if line.strip() and len(line.strip()) > 3
        ]

        # Take only the requested number
        suggestions = suggestions[:num_suggestions]

        logger.info(f"Generated {len(suggestions)} LLM suggestions for query: {user_query[:50]}...")
        return suggestions

    except Exception as e:
        logger.error(f"Error generating LLM suggestions: {e}")
        # Fallback to simple suggestions if LLM fails
        return _get_fallback_suggestions(table_name, num_suggestions)


def _get_related_schemas(current_table: Optional[str]) -> str:
    """
    Gets a brief summary of other available tables for cross-topic suggestions.
    """
    table_summaries = {
        "DailyPerformanceSummary": "Daily visits, revenue, transactions by date",
        "MonthlyPerformanceSummary": "Monthly aggregates (visits, revenue) by year/month",
        "CustomerSummary": "Customer segments, lifetime value, avg order value",
        "MerchantSummary": "Overall merchant stats (total customers, revenue, branches)",
        "LoyaltyProgramSummary": "Points, rewards, gifts redemption stats",
        "CampaignSummary": "Campaign performance, redemption rates",
        "GeographicPerformanceSummary": "Branch-level performance comparison",
        "PickupOrderSummary": "Order status breakdown (accepted, rejected, etc.)",
        "PaymentAnalyticsSummary": "Payment methods breakdown",
    }

    related = []
    for table, summary in table_summaries.items():
        if table != current_table:
            related.append(f"- {table}: {summary}")

    return "\n".join(related[:5])  # Limit to 5 related tables


def _get_fallback_suggestions(table_name: Optional[str], num_suggestions: int) -> List[str]:
    """
    Simple fallback suggestions if LLM fails.
    """
    fallbacks = {
        "DailyPerformanceSummary": ["Compare to last month", "Show by branch", "Best performing day"],
        "MonthlyPerformanceSummary": ["Year over year comparison", "Show monthly trend", "Best month"],
        "CustomerSummary": ["Segment breakdown", "Lost customers count", "Top customers"],
        "LoyaltyProgramSummary": ["Points redemption rate", "Rewards breakdown", "Active members"],
        "CampaignSummary": ["Best performing campaign", "Redemption rates", "Active campaigns"],
        "GeographicPerformanceSummary": ["Best branch", "Revenue by branch", "Branch comparison"],
        "PickupOrderSummary": ["Order status breakdown", "Rejected orders", "Acceptance rate"],
    }

    default = ["Show revenue trend", "Customer segments", "Branch comparison"]

    suggestions = fallbacks.get(table_name, default)
    return suggestions[:num_suggestions]


def format_suggestions_for_display(suggestions: List[str]) -> str:
    """
    Formats suggestions as a simple text list (fallback for non-JS clients).

    Args:
        suggestions: List of suggestion strings

    Returns:
        Formatted string with suggestions
    """
    if not suggestions:
        return ""

    lines = ["\n**You might also want to know:**"]
    for suggestion in suggestions:
        lines.append(f"• {suggestion}")

    return "\n".join(lines)
