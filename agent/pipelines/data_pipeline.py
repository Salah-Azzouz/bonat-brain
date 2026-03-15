"""
Data Analysis Pipeline

This module extracts the data analysis workflow from LangGraph into a callable function.
It executes all the existing nodes sequentially without the LangGraph state machine.
"""

import logging
import re
from decimal import Decimal
from typing import Dict, List, Optional

# Pre-warm the semantic router at import time (embeds utterances once).
# This avoids a ~500ms cold start on the first user request.
try:
    from agent.nodes.semantic_router import get_semantic_router
    get_semantic_router()
except Exception as e:
    logging.warning(f"[Data Pipeline] Semantic router warmup failed (will retry on first request): {e}")


# Time reference patterns — detects when a question mentions a specific time period
_TIME_PATTERNS = re.compile(
    r'(?:last|past|previous|this)\s+(?:week|month|year|quarter|7\s+days|30\s+days|90\s+days)'
    r'|(?:yesterday|today|tonight|tomorrow)'
    r'|(?:january|february|march|april|may|june|july|august|september|october|november|december)'
    r'|(?:jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+\d'
    r'|\b20[12]\d\b'  # years 2010-2029
    r'|(?:in|for|during|since)\s+(?:the\s+)?(?:last|past)'
    r'|\bآخر\s+(?:أسبوع|شهر|سنة)\b'  # Arabic: last week/month/year
    r'|\bهذا\s+(?:الأسبوع|الشهر)\b'  # Arabic: this week/month
    r'|\bالشهر\s+الماضي\b',  # Arabic: last month
    re.IGNORECASE
)


def _has_time_reference(text: str) -> bool:
    """Check if a question contains time period references."""
    return bool(_TIME_PATTERNS.search(text))


def _should_retry_with_fallback(execution_result: dict, state: dict) -> bool:
    """
    Determine if the query result warrants retrying with the fallback table.

    Retry triggers:
    - All result values are NULL (aggregation found nothing)
    - Row count is 0 (no matching rows)
    - Query timed out

    NOT a retry trigger:
    - Data exists but values are legitimately zero (e.g., 0 visits)
    - Non-empty result with real data
    """
    if not execution_result or not execution_result.get("success"):
        return False  # Query itself failed — fix_query already handled this

    # No fallback available → nothing to retry with
    if not state.get("fallback_table"):
        return False

    raw_data = execution_result.get("data", [])
    row_count = execution_result.get("row_count", 0)

    # Trigger: zero rows returned
    if row_count == 0 or not raw_data:
        return True

    # Trigger: all values in first row are NULL
    if raw_data and len(raw_data) > 0:
        first_row = raw_data[0]
        if isinstance(first_row, dict):
            if all(v is None for v in first_row.values()):
                return True

    return False


def _compute_quality_score(state: dict, execution_result: dict) -> float:
    """
    Compute a 0.0-1.0 quality score for a completed pipeline execution.

    Signals that decrease score:
    - Self-correction was used (fallback table)
    - Retries were needed
    - Result was partially truncated
    - Scope warning (lifetime table with time question)
    """
    score = 1.0

    # Penalty: self-correction happened (fallback was used)
    if state.get("query_source") == "fallback":
        score -= 0.3

    # Penalty: retries were needed
    retry_count = state.get("retry_count", 0)
    if retry_count > 0:
        score -= 0.15 * retry_count

    # Penalty: partial/truncated result
    if execution_result and execution_result.get("partial"):
        score -= 0.1

    # Penalty: scope warning (lifetime table with time question)
    if state.get("scope_warning"):
        score -= 0.2

    return max(0.0, min(1.0, score))


def execute_data_pipeline(
    user_question: str,
    merchant_id: str,
    history: Optional[List] = None,
    intent_category: Optional[str] = None,
) -> Dict:
    """
    Executes the complete data analysis pipeline.

    This function runs through all the existing nodes in sequence:
    1. Security check - Validate merchant isolation (inline)
    2. select_table - Choose the appropriate database table
    3. validate_request - Check if data is available
    4. create_query - Generate SQL query
    5. censor_query - Security check on the SQL
    6. execute_query - Run the query (with retry logic)
    7. fix_query - Fix errors if execution fails

    Note: analyze_data step removed - main agent handles response formatting

    Args:
        user_question: The user's question about their business data
        merchant_id: The merchant's unique identifier for data isolation
        history: Optional conversation history for context

    Returns:
        Dict with:
            - success: bool indicating if pipeline completed successfully
            - response: str with the natural language answer
            - data: Optional dict with raw data for validation
            - error: Optional str with error message if failed
    """
    logging.info(f"[Data Pipeline] Starting for merchant: {merchant_id}, question: {user_question}")

    # Initialize state (same as LangGraph state)
    from agent.config import get_merchant_now
    _now = get_merchant_now()
    state = {
        "user_prompt": user_question,
        "merchant_id": merchant_id,
        "history": history or [],
        "current_date": _now.strftime("%Y-%m-%d"),
        "current_day_name": _now.strftime("%A"),
        "intent_category": intent_category,
    }

    try:
        # ═══════════════════════════════════════════════════════════
        # STEP 0: Semantic Cache Check
        # ═══════════════════════════════════════════════════════════
        from agent.semantic_cache import get_semantic_cache

        cache_hit = get_semantic_cache().get(user_question, str(merchant_id))
        if cache_hit:
            logging.info(
                f"[Data Pipeline] Cache hit (score={cache_hit.score:.3f}) — "
                f"returning cached result"
            )
            return cache_hit.result

        # ═══════════════════════════════════════════════════════════
        # STEP 1: Security Check & Pass-through
        # ═══════════════════════════════════════════════════════════
        # The main agent already reformulates the question when calling query_db,
        # so we skip the LLM rewrite (confirm_meaning) to avoid double-rewriting
        # which strips routing keywords. We keep the merchant_id security check.
        logging.info("[Data Pipeline] Step 1: Security check (no LLM rewrite)...")
        session_merchant_id = str(state.get("merchant_id"))
        pattern = r'merchant.*?[=\s](\d+)'
        matches = re.findall(pattern, user_question, re.IGNORECASE)

        for match in matches:
            if match != session_merchant_id:
                error_message = (
                    "I am sorry, but I cannot process this request. You are only "
                    "authorized to access data for your own merchant account."
                )
                logging.warning(f"Security leak attempt blocked for merchant {session_merchant_id}.")
                return {
                    "success": False,
                    "response": error_message,
                    "data": None,
                    "error": error_message
                }

        # Pass the question through directly — no LLM rewriting
        state["confirmed_meaning"] = user_question
        state["error_message"] = None

        # ═══════════════════════════════════════════════════════════
        # STEP 2: Select Table
        # ═══════════════════════════════════════════════════════════
        from agent.nodes.select_table import select_table

        logging.info("[Data Pipeline] Step 2: Selecting table...")
        state.update(select_table(state))

        if not state.get("selected_table"):
            logging.warning("[Data Pipeline] select_table failed: No table selected")
            return {
                "success": False,
                "response": "I couldn't determine which data table to use for your question. Could you rephrase?",
                "data": None,
                "error": "No table selected"
            }

        logging.info(f"[Data Pipeline] Selected table: {state['selected_table']}")

        # CustomerSummary is a large table — retrying with LLM-generated fixes
        # rarely helps. Fail fast instead.
        table = state.get("selected_table", "")
        max_retries = 1 if table == "CustomerSummary" else 2

        # ═══════════════════════════════════════════════════════════
        # STEP 2b: Early Scope Detection (Lifetime Table + Time Question)
        # ═══════════════════════════════════════════════════════════
        # If the selected table has no time column AND the question mentions
        # a time period, set the scope_warning NOW — before validate_request.
        # This ensures the warning is available even if validate_request
        # short-circuits with "no data" (e.g., ec-02, ec-06).
        from agent.nodes.query_schema import TABLE_METADATA

        table_meta = TABLE_METADATA.get(table, {})
        time_col = table_meta.get('time_column')

        if not time_col and _has_time_reference(user_question):
            state["scope_warning"] = (
                f"⚠️ DATA SCOPE: The {table} table contains LIFETIME totals only "
                f"and cannot be filtered to a specific time period. "
                f"The results below are ALL-TIME data, not limited to the requested dates. "
                f"You MUST tell the user this is lifetime data, NOT data for their requested time period."
            )
            logging.info(f"[Data Pipeline] Early scope warning set for lifetime table {table}")

        # ═══════════════════════════════════════════════════════════
        # STEP 3: Validate Request (Data Availability Check)
        # ═══════════════════════════════════════════════════════════
        from agent.nodes.validate_request import validate_request

        logging.info("[Data Pipeline] Step 3: Validating request...")
        state.update(validate_request(state))

        validation_result = state.get("validation_result", "").strip().upper()

        if validation_result != "YES":
            # Data not available - return a definitive message (not a suggestion to retry)
            table = state.get("selected_table", "unknown")
            message = state.get("data_availability_message", "The requested data is not available.")

            # Include scope warning if this is a lifetime table with a time-filtered question
            scope_prefix = ""
            if state.get("scope_warning"):
                scope_prefix = f"{state['scope_warning']}\n\n"

            definitive_message = (
                f"{scope_prefix}"
                f"DEFINITIVE ANSWER: The {table} table has no data for your merchant account. "
                f"You don't have {table.replace('Summary', '').lower()} data available yet. "
                f"This is the CORRECT table for this question — do NOT retry with a different table."
            )
            logging.info(f"[Data Pipeline] Data not available: {definitive_message}")
            return {
                "success": True,  # Not an error, just no data
                "response": definitive_message,
                "data": None,
                "error": None
            }

        # ═══════════════════════════════════════════════════════════
        # STEP 4: Create Query (SQL Generation via LLM)
        # ═══════════════════════════════════════════════════════════
        from agent.nodes.create_query import create_query

        logging.info("[Data Pipeline] Step 4: Creating query...")
        state.update(create_query(state))
        state["query_source"] = state.get("query_source", "structured")

        # Check for error_message from create_query (e.g., non-existent column detected)
        # With the new structured output approach, this only triggers if BOTH
        # structured output AND legacy fallback failed — a rare edge case.
        # Instead of hard-failing, we let it through to execute_query/fix_query
        # which may still recover via the fix_query LLM retry loop.
        if state.get("error_message") and not state.get("generated_query"):
            logging.error(f"[Data Pipeline] create_query failed completely: {state['error_message']}")
            return {
                "success": False,
                "response": f"⚠️ DATA LIMITATION: {state['error_message']}",
                "data": None,
                "error": state["error_message"]
            }
        elif state.get("error_message"):
            # Has error_message but also has a generated_query — let execute_query try it
            logging.warning(f"[Data Pipeline] create_query has warnings but generated query — continuing: {state['error_message']}")
            state["error_message"] = None  # Clear so censor_query doesn't fail

        if not state.get("generated_query"):
            logging.warning("[Data Pipeline] create_query failed: No query generated")
            return {
                "success": False,
                "response": "I couldn't generate a query for your question.",
                "data": None,
                "error": "Query generation failed"
            }

        logging.info(f"[Data Pipeline] Generated query: {state['generated_query'][:100]}...")

        # ═══════════════════════════════════════════════════════════
        # STEP 5: Censor Query (Security Check)
        # ═══════════════════════════════════════════════════════════
        from agent.nodes.censor_query import censor_query

        logging.info("[Data Pipeline] Step 5: Censoring query...")
        state.update(censor_query(state))

        if state.get("error_message"):
            logging.warning(f"[Data Pipeline] censor_query failed: {state['error_message']}")
            return {
                "success": False,
                "response": state["error_message"],
                "data": None,
                "error": state["error_message"]
            }

        # ═══════════════════════════════════════════════════════════
        # STEP 6: Execute Query (With Retry Logic)
        # ═══════════════════════════════════════════════════════════
        from agent.nodes.execute_query import execute_query
        from agent.nodes.fix_query import fix_query

        retry_count = 0

        while retry_count <= max_retries:
            logging.info(f"[Data Pipeline] Step 6: Executing query (attempt {retry_count + 1}/{max_retries + 1})...")
            state.update(execute_query(state))

            execution_result = state.get("execution_result", {})

            if execution_result.get("success"):
                logging.info("[Data Pipeline] Query executed successfully")
                break  # Success!

            # Query failed
            logging.warning(f"[Data Pipeline] Query execution failed: {execution_result.get('error')}")

            # Don't retry timeout queries — they'll just timeout again
            if execution_result.get("timeout"):
                error_msg = execution_result.get("error", "Query timed out")
                logging.error(f"[Data Pipeline] Query timed out — skipping retries: {error_msg}")
                timeout_response = (
                    f"DEFINITIVE ANSWER: The query on {table} timed out because this table is very large. "
                    f"This is the CORRECT and ONLY table for this question — do NOT call query_db again. "
                    f"Any other table will give WRONG data. "
                    f"Tell the user: 'The query timed out on {table} due to its large size. "
                    f"Please try a narrower time range (e.g., last week instead of this month).'"
                )
                return {
                    "success": True,  # Treated as final answer — prevents agent retry
                    "response": timeout_response,
                    "data": None,
                    "error": None
                }

            if retry_count >= max_retries:
                # Max retries reached
                error_msg = execution_result.get("error", "Query execution failed")
                logging.error(f"[Data Pipeline] Max retries reached. Final error: {error_msg}")
                return {
                    "success": False,
                    "response": "I encountered an issue executing the query. Please try rephrasing your question.",
                    "data": None,
                    "error": error_msg
                }

            # Try to fix the query
            logging.info("[Data Pipeline] Attempting to fix query...")
            state["retry_count"] = retry_count
            state.update(fix_query(state))
            retry_count += 1

        # ═══════════════════════════════════════════════════════════
        # STEP 6b: Self-Correction — Retry with fallback table
        # ═══════════════════════════════════════════════════════════
        # If primary table returned empty/NULL results AND a fallback
        # table exists, re-run steps 2b-6 with the fallback.
        if _should_retry_with_fallback(execution_result, state):
            fallback = state.get("fallback_table")
            fallback_schema = state.get("fallback_schema")
            if fallback and fallback != state.get("selected_table") and fallback_schema:
                original_table = state["selected_table"]
                logging.info(
                    f"[Data Pipeline] Self-correction: {original_table} → {fallback} "
                    f"(primary returned empty/NULL)"
                )
                state["selected_table"] = fallback
                state["table_schema"] = fallback_schema
                # Clear old query artifacts
                state.pop("generated_query", None)
                state.pop("execution_result", None)
                state.pop("error_message", None)
                state.pop("scope_warning", None)
                # Clear fallback to prevent infinite loop
                state.pop("fallback_table", None)
                state.pop("fallback_schema", None)

                # Re-check scope warning for fallback table
                fb_meta = TABLE_METADATA.get(fallback, {})
                fb_time_col = fb_meta.get('time_column')
                if not fb_time_col and _has_time_reference(user_question):
                    state["scope_warning"] = (
                        f"⚠️ DATA SCOPE: The {fallback} table contains LIFETIME totals only "
                        f"and cannot be filtered to a specific time period."
                    )

                # Re-run: validate → create → censor → execute
                state.update(validate_request(state))
                if state.get("validation_result", "").strip().upper() == "YES":
                    state.update(create_query(state))
                    if state.get("generated_query") and not state.get("error_message"):
                        state.update(censor_query(state))
                        if not state.get("error_message"):
                            state.update(execute_query(state))
                            execution_result = state.get("execution_result", {})
                            if execution_result.get("success"):
                                table = fallback
                                logging.info(
                                    f"[Data Pipeline] Self-correction SUCCESS: "
                                    f"{original_table} → {fallback}"
                                )

        # ═══════════════════════════════════════════════════════════
        # STEP 6c: Quality-Gated Auto-learn (Function RAG)
        # ═══════════════════════════════════════════════════════════
        # Only learn if we got meaningful data AND quality score is high enough
        if not _should_retry_with_fallback(execution_result, state):
            try:
                from agent.example_store import get_example_store

                # Compute quality score based on pipeline signals
                quality_score = _compute_quality_score(state, execution_result)

                get_example_store().add_example(
                    question=user_question,
                    table=state.get("selected_table", ""),
                    sql=state.get("generated_query", ""),
                    quality_score=quality_score,
                )
            except Exception as e:
                logging.debug(f"[Data Pipeline] Example store auto-learn failed (non-critical): {e}")

        # ═══════════════════════════════════════════════════════════
        # STEP 7: Return Raw Data (Main Agent Handles Formatting)
        # ═══════════════════════════════════════════════════════════
        logging.info("[Data Pipeline] Pipeline completed successfully - returning raw data")

        # Format the raw data for the main agent
        raw_data = execution_result.get("data", [])
        row_count = execution_result.get("row_count", 0)

        # ═══════════════════════════════════════════════════════════
        # CRITICAL: Handle NULL results from aggregation queries
        # When SUM/COUNT returns NULL, it means no matching rows, NOT "no data exists"
        # ═══════════════════════════════════════════════════════════
        null_result_context = ""
        has_all_null_values = False

        if raw_data and len(raw_data) > 0:
            # Check if all values in the result are None/NULL
            first_row = raw_data[0]
            if isinstance(first_row, dict):
                all_values_null = all(v is None for v in first_row.values())
                if all_values_null:
                    has_all_null_values = True
                    # Check if this is a time-filtered query
                    query_lower = state.get('generated_query', '').lower()
                    is_time_filtered = any(term in query_lower for term in [
                        'performance_date', 'curdate', 'date_sub', 'interval',
                        'today', 'yesterday', 'last_', 'this_', 'year', 'month'
                    ])

                    if is_time_filtered:
                        null_result_context = """
**⚠️ IMPORTANT CONTEXT FOR AGENT:**
The query returned NULL values. This means NO ACTIVITY was recorded for the SPECIFIC TIME PERIOD requested.
This does NOT mean the merchant has no data at all - they likely have historical data from other periods.

**How to respond:**
- DO NOT say "no data available" or "لا توجد بيانات"
- DO say "No [metric] recorded for [time period]" or "لم يتم تسجيل [المقياس] في [الفترة الزمنية]"
- OFFER to show data from a different time period (e.g., "Would you like to see last week's data instead?")

Example good response: "No customers visited today (Dec 9, 2025). Would you like to see data from the last 7 days instead?"
Example bad response: "No data available for customers today." ← This sounds like the system has no data!
"""
                    else:
                        null_result_context = """
**⚠️ IMPORTANT CONTEXT FOR AGENT:**
The query returned NULL values. This typically means no matching records exist for the query criteria.
Present this clearly without saying "no data available" which sounds like a system error.
"""

        # ═══════════════════════════════════════════════════════════
        # CRITICAL: Handle all-zero results — merchant may not have data yet
        # Distinct from NULL (no rows matched): zero means rows exist but
        # all numeric columns are 0, which often indicates unpopulated data.
        # ═══════════════════════════════════════════════════════════
        all_zeros_context = ""
        if raw_data and len(raw_data) > 0 and not has_all_null_values:
            first_row = raw_data[0]
            if isinstance(first_row, dict):
                numeric_vals = [v for v in first_row.values() if isinstance(v, (int, float, Decimal))]
                if numeric_vals and all(v == 0 for v in numeric_vals):
                    all_zeros_context = (
                        "\n**⚠️ ALL-ZERO RESULT:** Every numeric value is 0. "
                        "This likely means the merchant doesn't have this data populated yet. "
                        "Present it as: 'You don't have [metric] data in your account yet' or "
                        "'No [metric] has been recorded.' — do NOT present 0 as a meaningful business metric.\n"
                    )
                    logging.info(f"[Data Pipeline] All-zero result detected for {table}")

        # Include partial-chunk warning if applicable
        chunks_note = ""
        if execution_result.get("partial"):
            chunks_note = f"\n{execution_result['chunks_note']}\n"

        # Build scope warning context if lifetime table was time-filtered
        scope_warning_context = ""
        if state.get("scope_warning"):
            scope_warning_context = (
                f"⚠️ IMPORTANT — READ THIS FIRST:\n"
                f"{state['scope_warning']}\n"
                f"You MUST start your response by explaining this limitation to the user "
                f"BEFORE showing any numbers.\n\n"
            )

        # Build a structured response with the raw data
        response = f"""{scope_warning_context}**Query Results:**
Table: {state.get('selected_table')}
Rows returned: {row_count}
{null_result_context}{all_zeros_context}{chunks_note}
**Data:**
{raw_data}

**SQL Query Used:**
{state.get('generated_query', 'N/A')}
"""

        result = {
            "success": True,
            "response": response,
            "data": execution_result.get("data"),
            "error": None,
            "has_null_result": has_all_null_values
        }

        # ═══════════════════════════════════════════════════════════
        # STEP 7b: Cache successful result
        # ═══════════════════════════════════════════════════════════
        try:
            has_time_filter = bool(state.get("scope_warning") is None and
                                   TABLE_METADATA.get(table, {}).get("time_column"))
            get_semantic_cache().put(
                question=user_question,
                merchant_id=str(merchant_id),
                result=result,
                has_time_filter=has_time_filter,
            )
        except Exception as e:
            logging.debug(f"[Data Pipeline] Cache put failed (non-critical): {e}")

        return result

    except Exception as e:
        logging.error(f"[Data Pipeline] Unexpected error: {e}", exc_info=True)
        return {
            "success": False,
            "response": "An unexpected error occurred while processing your request.",
            "data": None,
            "error": str(e)
        }


