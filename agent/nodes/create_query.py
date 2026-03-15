import logging
import re
from datetime import timedelta
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from agent.config import get_llm
from .types import State

# ═══════════════════════════════════════════════════════════════════════════════
# NEW ARCHITECTURE: Structured Output Decomposition
# ═══════════════════════════════════════════════════════════════════════════════
# Instead of the LLM generating raw SQL, it outputs a structured QueryIntent
# (JSON), and deterministic code compiles it to valid MySQL.
# This eliminates column hallucination. Falls back to legacy on failure.
# See ARCHITECTURE_RESEARCH.md for the industry research behind this approach.

from .query_schema import (
    QueryIntent,
    build_table_query_intent,
    get_column_list_for_prompt,
    get_table_notes,
    get_time_column,
    get_time_presets_for_prompt,
    TABLE_METADATA,
)
from .compile_query import compile_to_sql

def create_query(state: State) -> dict:
    """
    Creates a SQL query using Structured Output Decomposition.

    Architecture:
    1. LLM outputs a QueryIntent (structured JSON) — picks columns, filters, grouping
    2. compile_to_sql() deterministically generates valid MySQL from the intent
    3. If anything fails → falls back to _create_query_legacy (raw SQL generation)

    This eliminates column hallucination because:
    - The LLM sees only allowlisted column names (not raw CREATE TABLE DDL)
    - The compiler validates every column before generating SQL
    - Date resolution is deterministic (presets like "last_7_days" → exact dates)
    """
    logging.info("--- Creating SQL Query (Structured Output) ---")

    table_name = state["selected_table"]
    question = state["confirmed_meaning"]
    merchant_id = state["merchant_id"]

    # Diagnostic logging for debugging eval failures
    current_date_log = state.get("current_date", "N/A")
    logging.info(f"[create_query] INPUT: table={table_name}, question={question[:100]}, date={current_date_log}")

    # Read date from state (set by data_pipeline)
    current_date = state.get("current_date")
    current_day_name = state.get("current_day_name")
    if not current_date:
        from agent.config import get_merchant_now
        _now = get_merchant_now()
        current_date = _now.strftime("%Y-%m-%d")
        current_day_name = _now.strftime("%A")

    # Check if this table has metadata for structured output
    if table_name not in TABLE_METADATA:
        logging.warning(
            f"Table {table_name} not in TABLE_METADATA — falling back to legacy"
        )
        return _create_query_legacy(state)

    # ═══ Step 0: Deterministic date resolution (BEFORE LLM) ═══
    # Resolve date expressions in code — the LLM should never interpret dates.
    resolved_time = _resolve_date_deterministic(question, current_date)
    if resolved_time:
        logging.info(f"[create_query] Deterministic date: {resolved_time}")

    try:
        # ═══ Step 1: Get structured output from LLM ═══
        intent = _get_structured_intent(
            question=question,
            table_name=table_name,
            current_date=current_date,
            current_day_name=current_day_name,
            resolved_time=resolved_time,
        )

        if intent is None:
            logging.warning("Structured output returned None — falling back to legacy")
            return _create_query_legacy(state)

        # ═══ Step 1b: Force-override LLM's time_range with deterministic result ═══
        if resolved_time:
            time_col = get_time_column(table_name)
            if time_col:
                intent.time_range = resolved_time
                logging.info(
                    f"[create_query] Overriding LLM time_range with deterministic: "
                    f"{resolved_time}"
                )

        # ═══ Step 2: Compile intent to SQL ═══
        result = compile_to_sql(
            intent=intent,
            table_name=table_name,
            merchant_id=merchant_id,
            current_date=current_date,
        )

        if result['error']:
            logging.warning(
                f"Compilation failed: {result['error']} — falling back to legacy"
            )
            return _create_query_legacy(state)

        query = result['query']
        scope_warning = result.get('scope_warning')
        logging.info(f"[create_query] PATH=structured | SQL: {query}")
        if scope_warning:
            logging.info(f"[create_query] Scope warning: {scope_warning}")

        ret = {
            "generated_query": query,
            "previous_query_metric": "",
            "previous_query_columns": query,
        }
        if scope_warning:
            ret["scope_warning"] = scope_warning
        return ret

    except Exception as e:
        logging.error(
            f"Structured output failed: {e} — falling back to legacy",
            exc_info=True,
        )
        return _create_query_legacy(state)


def _get_structured_intent(
    question: str,
    table_name: str,
    current_date: str,
    current_day_name: str,
    resolved_time=None,
) -> QueryIntent | None:
    """
    Ask the LLM to output a structured QueryIntent (not raw SQL).

    Uses OpenAI's structured output feature via LangChain's with_structured_output()
    to guarantee valid JSON conforming to the QueryIntent schema.
    """
    column_list = get_column_list_for_prompt(table_name)
    table_notes = get_table_notes(table_name)
    time_column = get_time_column(table_name)

    # Build time context
    if time_column:
        time_context = f"""## Time Filtering
This table supports time filtering (column: `{time_column}`).
{get_time_presets_for_prompt()}

Today is {current_date} ({current_day_name}).
If the question mentions a time period, set the time_range field with the appropriate preset.
For specific dates (e.g., "in March 2025"), use custom_start / custom_end.

**CRITICAL — ALWAYS use presets. NEVER use custom_start/custom_end for these:**
- "last 7 days" / "past 7 days" → preset "last_7_days"
- "past 2 weeks" / "last 2 weeks" / "last 14 days" → preset "last_14_days"
- "last 30 days" / "past 30 days" / "last month of data" → preset "last_30_days"
- "last 90 days" / "past 90 days" / "last 3 months of data" → preset "last_90_days"
- "last week" / "آخر أسبوع" / "الأسبوع الماضي" / "past week" / "previous week" → preset "last_week" (Mon-Sun)
- "last month" / "الشهر الماضي" / "آخر شهر" / "previous month" → preset "last_month"
- "this month" / "هذا الشهر" / "joined this month" / "this month so far" → preset "this_month"
- "this week" / "هذا الأسبوع" → preset "this_week"
- "today" / "اليوم" → preset "today"
- "yesterday" / "أمس" → preset "yesterday"
- "this year" / "هذه السنة" → preset "this_year"
- "last year" / "السنة الماضية" → preset "last_year"
- IMPORTANT: "last week" ≠ "last 7 days". "last week" = previous Mon-Sun. "last 7 days" = today - 7.
- NEVER compute date ranges manually. ALWAYS use a preset. Custom dates are ONLY for specific named dates like "March 2025" or "from Jan 1 to Feb 28"."""
    else:
        time_context = (
            "## Time Filtering\n"
            "This table contains LIFETIME data only — no date filtering possible.\n"
            "Do NOT set time_range. If the user asks for a time period, "
            "the data returned will be all-time totals."
        )

    # Add CustomerSummary performance warning
    perf_warning = ""
    if table_name == "CustomerSummary":
        perf_warning = """
### ⚠️ CRITICAL Performance Warning (CustomerSummary):
This table has 150K+ rows and queries WILL TIMEOUT without proper optimization.
MANDATORY RULES:
1. ALWAYS set time_range when the question mentions any time period (this month, last week, etc.)
2. For ANY question about customers registered/joined/signed up → ALWAYS use metrics: [{aggregation: "count", column: "*"}]
   This includes "show me", "list", "how many", "give me" — ALL patterns must use COUNT(*).
   Selecting individual customer rows will timeout or return incomplete data (LIMIT 100 vs 150K+ rows).
3. NEVER select individual columns like customer_name, customer_email, etc. — always use COUNT(*) or aggregation
4. Set limit to 100 maximum
5. If no time period is mentioned, still set time_range to avoid full table scan (default: last_30_days)

### Date Column Selection Rule (CustomerSummary):
The default time_range applies to `registration_date`. BUT:
- "registered", "joined", "signed up" → use time_range preset (applies to registration_date) ✓
- "visited", "visit", "active", "last visit" → do NOT use time_range. Instead, add FILTERS on `last_visit_date`:
  Add two FilterCondition entries: last_visit_date >= start_date AND last_visit_date < end_date.
  Compute the dates based on today's date and the requested period.
  Example: "loyal customers visited last month" with today = 2026-02-15:
  - filters: [{column: "loyalty_segment_id", operator: "=", value: "loyalCustomer"},
              {column: "last_visit_date", operator: ">=", value: "2026-01-01"},
              {column: "last_visit_date", operator: "<", value: "2026-02-01"}]
  - time_range: {} (empty — do NOT set preset)
  - metrics: [{aggregation: "count", column: "*", alias: "loyal_customers_visited"}]

Example intent for "Show me new customers who joined this month":
- metrics: [{aggregation: "count", column: "*", alias: "new_customers"}]
- time_range: {preset: "this_month"}
- filters: [] (idMerchant is auto-added)
- NOTE: Even though the user said "show me", we use COUNT because listing 150K+ rows is impractical
"""

    # DPS-specific aggregation rules
    branch_rule = ""
    if table_name == "DailyPerformanceSummary":
        branch_rule = """
### IMPORTANT — DailyPerformanceSummary Aggregation Rules:
1. **Branch Rule:** Unless the user explicitly asks for a branch breakdown (e.g., "by branch", "per branch", "which branch"),
   do NOT include `idBranch` or `branch_name` in `group_by` or `columns`.
   Just use SUM() on the metric columns — the result should be a single aggregated number per date.
2. **Daily Breakdown Rule:** When the user asks for "daily [metric]", "per day", "each day", "day by day",
   or "show me [metric] for [time period]" (implying they want to SEE the data over time):
   ALWAYS include `performance_date` in `group_by` to return one row per day.
   Example: "daily visits for past 2 weeks" → group_by: ["performance_date"], metrics: [{aggregation: "sum", column: "daily_visits"}]
   Example: "show me visits for last month" → group_by: ["performance_date"], metrics: [{aggregation: "sum", column: "daily_visits"}]
   Only return a single SUM (no group_by) when the user explicitly asks for a "total" (e.g., "total visits last month").
3. **"Total" means ALL-TIME SUM:** When the user asks for "total [metric]" without any time qualifier
   (e.g., "total online transactions", "total visits", "total revenue"), do NOT add a time_range.
   Leave time_range empty to aggregate across ALL dates. Use SUM() aggregation.
4. **COUNT(*) vs SUM():** This table has one row per branch per day. COUNT(*) counts ROWS, not the metric.
   For "how many transactions/orders/visits" → always use SUM(total_orders) or SUM(daily_visits), NOT COUNT(*).
5. **total_orders = online coupon transactions.** This column ALREADY represents online transactions.
   Do NOT add idBranch = -1 when the user asks about "online transactions" — that would double-filter.
   Only add idBranch filters when the user asks about a SPECIFIC branch or "online vs in-store" comparison.
"""

    # CampaignSummary-specific: per-campaign breakdown
    campaign_rule = ""
    if table_name == "CampaignSummary":
        campaign_rule = """
### IMPORTANT — CampaignSummary Breakdown Rules:
1. **Per-campaign breakdown:** When asked about "campaign rates", "campaign performance", "redemption rates",
   or any campaign metrics, ALWAYS include `campaign_title` in `group_by`.
   Use individual column values (e.g., `redemption_rate`), NOT AVG(redemption_rate).
   The user wants to see each campaign's performance, not a single average.
2. **Aggregation:** Only use SUM/COUNT for counts (e.g., total coupons_used across all campaigns).
   For rates and percentages (redemption_rate, campaign_roi), select them directly with aggregation="none".
3. **Ordering:** Always ORDER BY the most relevant metric DESC (e.g., redemption_rate DESC for rates,
   revenue_generated DESC for revenue). This ensures the most interesting campaigns appear first.
4. **Filter non-zero:** When showing rates, add a filter for redemption_rate > 0 to exclude campaigns
   with no redemptions (they clutter the results). Include total_coupons_issued to give context.
"""

    # MonthlyPerformanceSummary: always include year with month
    monthly_rule = ""
    if table_name == "MonthlyPerformanceSummary":
        monthly_rule = """
### IMPORTANT — MonthlyPerformanceSummary Rules:
1. **ALWAYS include `year` alongside `month`:** This table has data spanning multiple years.
   If you GROUP BY `month` without `year`, you will aggregate Jan 2024 + Jan 2025 + Jan 2026 together.
   → ALWAYS include `year` in BOTH `metrics` (as a column) AND `group_by`.
   → Example: "monthly visit trends" → metrics: [year, month, monthly_visits], group_by: [year, month]
2. **Ordering:** Default ORDER BY `year` DESC, `month` DESC (most recent first).
   For chronological trends, use ORDER BY `year` ASC, `month` ASC.
3. **Year filtering:** When user asks about a specific year (e.g., "2024 revenue"),
   add a filter: year = 2024. Still include `year` in group_by for consistency.
"""

    # Inject deterministic date hint if resolved
    date_hint = ""
    if resolved_time and get_time_column(table_name):
        if resolved_time.preset:
            date_hint = f"\n### ⚠️ PRE-RESOLVED DATE (use exactly):\ntime_range preset = \"{resolved_time.preset}\". Use this value. Do NOT compute dates yourself.\n"
        elif resolved_time.custom_start:
            date_hint = f"\n### ⚠️ PRE-RESOLVED DATE (use exactly):\ntime_range custom_start = \"{resolved_time.custom_start}\", custom_end = \"{resolved_time.custom_end}\". Use these values. Do NOT compute dates yourself.\n"

    prompt = f"""You are a data analyst. Given a user's question, output a structured query intent.

## Table: `{table_name}`

### Available Columns (ONLY use columns from this list):
{column_list}

### Table Notes:
{table_notes}
{perf_warning}
{branch_rule}
{campaign_rule}
{monthly_rule}
{time_context}
{date_hint}
### Instructions:
- Pick ONLY columns from the available list above
- Use aggregation (sum/count/avg) when the user asks for totals or averages
- Use 'count' with column='*' for COUNT(*) queries (e.g., "how many customers")
- For "per-segment breakdown" or "by branch" → set appropriate group_by
- For "top N" → set order_by + limit
- Do NOT include idMerchant in filters (it's auto-added)
- CRITICAL SEGMENT FILTERING (LoyaltyProgramSummary only):
  ⚠️ RULE 1 — BREAKDOWN / COMPARISON (highest priority):
  If the question contains ANY of: "breakdown", "vs", "and", "compare", "distribution",
  "new vs lost", "all segments", "new and lost", "segment counts", "each segment":
    → Filter: loyalty_segment_id != 'ALL'
    → Group by: loyalty_segment_id
    → This returns ALL 7 segments. The user reads the ones they want.
    → ⚠️ NEVER use IN (...) to cherry-pick segments for comparisons. ALWAYS use != 'ALL'.
    → Example: "new vs lost" → WHERE loyalty_segment_id != 'ALL' GROUP BY loyalty_segment_id
  RULE 2 — SINGLE segment (e.g., 'how many Super Fans', 'lost customer count'):
    → Filter: loyalty_segment_id = '<exact_id>'
  RULE 3 — MERCHANT TOTALS (e.g., 'total members', 'overall'):
    → Filter: loyalty_segment_id = 'ALL'
  Exact segment IDs: superFan, loyalCustomer, regularCustomer, newCustomer, lostCustomer, potentialCustomer, birthday, ALL.

### User's Question:
{question}"""

    try:
        llm = get_llm()

        # Use table-specific model with enum-constrained columns
        # (constrained decoding — LLM physically cannot hallucinate column names)
        TableQueryIntent = build_table_query_intent(table_name)
        structured_llm = llm.with_structured_output(TableQueryIntent)
        intent = structured_llm.invoke(prompt)

        if intent:
            # Post-process: normalize custom dates to presets when they match
            intent = _normalize_time_range(intent, question, current_date)

            logging.info(
                f"[Structured Output] LLM intent (enum-constrained): "
                f"metrics={[m.column for m in intent.metrics]}, "
                f"filters={len(intent.filters)}, "
                f"group_by={intent.group_by}, "
                f"time_range={intent.time_range}"
            )
        return intent

    except Exception as e:
        logging.error(f"[Structured Output] LLM structured output failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Post-Processing: Normalize custom dates → presets
# ═══════════════════════════════════════════════════════════════════════════════
#
# The LLM sometimes computes custom date ranges instead of using presets.
# This causes date drift (off-by-one, wrong week start, etc.).
#
# Two-layer detection:
# 1. Text-based: check question for natural language patterns like "last 30 days"
# 2. Date-based: compare custom_start/custom_end to what each preset would produce
#    (handles cases where main agent reformulates "this month" into explicit dates)

_TEXT_PRESET_PATTERNS = [
    # ── ORDER MATTERS: more specific patterns first ──
    # Explicit day counts
    (r'\b(?:last|past)\s+(?:2\s+weeks?|14\s+days?)\b', 'last_14_days'),
    (r'\b(?:last|past)\s+30\s+days?\b', 'last_30_days'),
    (r'\b(?:last|past)\s+90\s+days?\b', 'last_90_days'),
    (r'\b(?:last|past)\s+7\s+days?\b', 'last_7_days'),
    # "past week" / "this past week" = last 7 days (NOT Mon-Sun)
    (r'\b(?:this\s+)?past\s+week\b', 'last_7_days'),
    # "last week" / "previous week" = previous Mon-Sun
    (r'\b(?:last|previous)\s+week\b', 'last_week'),
    # Arabic week
    (r'\bآخر\s*أسبوع\b', 'last_week'),
    (r'\bالأسبوع\s+الماضي\b', 'last_week'),
    # Month patterns
    (r'\b(?:last|past|previous)\s+month\b', 'last_month'),
    (r'\bالشهر\s+الماضي\b', 'last_month'),
    (r'\bآخر\s*شهر\b', 'last_month'),
    (r'\bthis\s+month\b', 'this_month'),
    (r'\b(?:joined|registered|signed\s+up)\s+this\s+month\b', 'this_month'),
    (r'\bهذا\s+الشهر\b', 'this_month'),
    # Week/year patterns
    (r'\bthis\s+week\b', 'this_week'),
    (r'\bهذا\s+الأسبوع\b', 'this_week'),
    (r'\bthis\s+year\b', 'this_year'),
    (r'\blast\s+year\b', 'last_year'),
    # Day patterns
    (r'\b(?:today|اليوم)\b', 'today'),
    (r'\b(?:yesterday|أمس)\b', 'yesterday'),
]


def _build_month_name_patterns(current_date_str: str) -> list[tuple[str, str]]:
    """
    Build dynamic patterns that map month names to presets based on current date.

    E.g., if today = 2026-02-15:
      "january 2026" → last_month
      "february 2026" → this_month
      "december 2025" → (no preset — too far back)

    This catches the main agent's reformulation: "last month" → "January 2026".
    """
    from datetime import date as _date
    d = _date.fromisoformat(current_date_str)
    patterns = []

    # Current month name → this_month
    current_month_name = d.strftime('%B').lower()
    patterns.append(
        (rf'\b{current_month_name}\s+{d.year}\b', 'this_month')
    )

    # Previous month name → last_month
    first_of_this = d.replace(day=1)
    last_of_prev = first_of_this - timedelta(days=1)
    prev_month_name = last_of_prev.strftime('%B').lower()
    patterns.append(
        (rf'\b{prev_month_name}\s+{last_of_prev.year}\b', 'last_month')
    )

    # Previous month without year (e.g., just "January") — only match if
    # it's unambiguously the previous month (not mentioned with a different year)
    patterns.append(
        (rf'\b(?:for|in|during|of)\s+{prev_month_name}\b', 'last_month')
    )

    return patterns

# Presets to check for date-based matching (most common ones)
_DATE_MATCH_PRESETS = [
    'today', 'yesterday', 'last_7_days', 'last_14_days', 'this_week', 'last_week',
    'this_month', 'last_month', 'last_30_days', 'last_90_days',
    'this_year', 'last_year',
]


def _resolve_date_deterministic(question: str, current_date: str):
    """
    Deterministically resolve date expressions to a TimeRange BEFORE the LLM.

    This is the authoritative date resolver — its output overrides whatever
    the LLM generates. Handles:
    - Preset patterns ("last 7 days", "past week", "this month", etc.)
    - Day-of-week ("last Tuesday", "past Monday")
    - Month + year ("January 2025", "March 2024")
    - Arabic patterns ("آخر أسبوع", "الشهر الماضي")

    Returns a TimeRange or None if no known date expression detected.
    """
    from .query_schema import TimeRange
    from datetime import date as _date

    question_lower = question.lower()

    # ── Layer 1: Static preset patterns ──
    for pattern, preset in _TEXT_PRESET_PATTERNS:
        if re.search(pattern, question_lower) or re.search(pattern, question):
            logging.info(f"[date_resolver] Deterministic match: '{preset}' from pattern")
            return TimeRange(preset=preset)

    # ── Layer 2: Dynamic month-name patterns ──
    for pattern, preset in _build_month_name_patterns(current_date):
        if re.search(pattern, question_lower):
            logging.info(f"[date_resolver] Month-name match: '{preset}'")
            return TimeRange(preset=preset)

    # ── Layer 3: Day-of-week ("last Tuesday", "past Monday") ──
    day_match = re.search(
        r'(?:last|past|previous)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
        question_lower
    )
    if day_match:
        day_name = day_match.group(1)
        d = _date.fromisoformat(current_date)
        day_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        target_dow = day_map[day_name]
        days_back = (d.weekday() - target_dow) % 7
        if days_back == 0:
            days_back = 7  # "last Tuesday" on a Tuesday = 7 days ago
        target_date = (d - timedelta(days=days_back)).isoformat()
        logging.info(f"[date_resolver] Day-of-week: 'last {day_name}' → {target_date}")
        return TimeRange(custom_start=target_date, custom_end=target_date)

    # ── Layer 4: Month + year ("January 2025", "in March 2024") ──
    month_year_match = re.search(
        r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})\b',
        question_lower
    )
    if month_year_match:
        from calendar import monthrange as _monthrange
        month_names = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12
        }
        m = month_names[month_year_match.group(1)]
        y = int(month_year_match.group(2))
        _, last_day = _monthrange(y, m)
        start = f"{y}-{m:02d}-01"
        end = f"{y}-{m:02d}-{last_day:02d}"
        logging.info(f"[date_resolver] Month+year: '{month_year_match.group(0)}' → {start} to {end}")
        return TimeRange(custom_start=start, custom_end=end)

    return None


def _normalize_time_range(intent, question: str, current_date: str):
    """
    Normalize LLM-generated time ranges to use presets when possible.

    Two detection layers:
    1. Text patterns in the question (e.g., "last 30 days" → last_30_days)
    2. Date matching: if LLM used custom dates that match a known preset's
       output, swap to the preset (handles reformulated questions)

    This prevents off-by-one errors, wrong week boundaries, etc.
    """
    from .compile_query import resolve_time_preset

    # ── Layer 1: Text-based detection ──
    question_lower = question.lower()
    text_detected = None

    # Static patterns (e.g., "last month", "this week")
    for pattern, preset in _TEXT_PRESET_PATTERNS:
        if re.search(pattern, question_lower) or re.search(pattern, question):
            text_detected = preset
            break

    # Dynamic month-name patterns (e.g., "January 2026" → last_month)
    if not text_detected:
        for pattern, preset in _build_month_name_patterns(current_date):
            if re.search(pattern, question_lower):
                text_detected = preset
                logging.info(f"[normalize] Month-name pattern matched: '{preset}' from question")
                break

    # ── Layer 2: Date-based detection (for reformulated questions) ──
    date_detected = None
    if (intent.time_range
            and intent.time_range.custom_start
            and not intent.time_range.preset):
        custom_start = intent.time_range.custom_start
        custom_end = intent.time_range.custom_end or current_date
        for preset_name in _DATE_MATCH_PRESETS:
            try:
                preset_start, preset_end = resolve_time_preset(preset_name, current_date)
                # Allow 2-day tolerance on both start and end (LLM off-by-one + timezone drift)
                if _dates_close(custom_start, preset_start, tolerance=2) and _dates_close(custom_end, preset_end, tolerance=2):
                    date_detected = preset_name
                    break
            except Exception:
                continue

    # Pick the best detection (text takes priority, then date)
    detected_preset = text_detected or date_detected

    if not detected_preset:
        return intent  # No preset found — leave as-is

    if intent.time_range is None:
        logging.info(
            f"[normalize] LLM omitted time_range but detected preset '{detected_preset}' — adding"
        )
        from .query_schema import TimeRange
        intent.time_range = TimeRange(preset=detected_preset)
        return intent

    if intent.time_range.preset:
        # LLM already used a preset — only override if text detection disagrees
        if text_detected and intent.time_range.preset != text_detected:
            logging.warning(
                f"[normalize] LLM used preset '{intent.time_range.preset}' "
                f"but text implies '{text_detected}' — overriding"
            )
            intent.time_range.preset = text_detected
            intent.time_range.custom_start = None
            intent.time_range.custom_end = None
        return intent

    # LLM used custom dates — swap to detected preset
    source = "text" if text_detected else "date-match"
    logging.warning(
        f"[normalize] LLM used custom dates ({intent.time_range.custom_start} to "
        f"{intent.time_range.custom_end}) but {source} detection found preset "
        f"'{detected_preset}' — swapping to preset"
    )
    intent.time_range.preset = detected_preset
    intent.time_range.custom_start = None
    intent.time_range.custom_end = None

    return intent


def _dates_close(date_a: str, date_b: str, tolerance: int = 1) -> bool:
    """Check if two date strings are within `tolerance` days of each other."""
    from datetime import date as _date
    try:
        da = _date.fromisoformat(date_a)
        db = _date.fromisoformat(date_b)
        return abs((da - db).days) <= tolerance
    except (ValueError, TypeError):
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY CODE — Preserved as fallback
# Everything below is the original raw SQL generation approach.
# ═══════════════════════════════════════════════════════════════════════════════

_SQL_KEYWORDS = frozenset({
    "select", "from", "where", "and", "or", "not", "null", "as", "distinct",
    "desc", "asc", "limit", "by", "in", "between", "like", "is", "case",
    "when", "then", "else", "end", "interval", "day", "month", "year",
    "date_sub", "curdate", "sum", "count", "avg", "max", "min", "having",
    "group", "order", "on", "join", "left", "right", "inner", "outer",
    "cross", "union", "all", "exists", "any", "true", "false", "if",
    "into", "values", "set", "update", "delete", "insert", "create",
    "table", "index", "alter", "drop", "with", "recursive", "over",
    "partition", "row", "rows", "range", "unbounded", "preceding",
    "following", "current", "date", "time", "timestamp", "now",
    "date_format", "yearweek", "concat", "cast", "convert", "coalesce",
    "ifnull", "nullif",
})


# Per-table column warnings injected dynamically into the SQL generation prompt.
# Only the selected table's warnings are included — keeps the prompt focused and short.
_TABLE_COLUMN_WARNINGS = {
    'DailyPerformanceSummary': """
**⚠️ CRITICAL COLUMN NAMES:**
- Date column: `performance_date` (**NOT** `date`)
- Visits column: `daily_visits` (**NOT** `total_visits` or `visit_count`)
- `total_orders` = online coupon transactions (**NOT** pickup orders)
- `customer_segment` does NOT exist in this table
- `online_transactions` does NOT exist — use `total_orders`
- Revenue column: `total_revenue` (**NOT** `daily_revenue` or `revenue`)
- Channel: `idBranch = -1` (online), `idBranch > 0` (in-store), omit for all channels
- CRITICAL: `total_orders` already represents online coupon transactions. Do NOT add `idBranch = -1` when asking about "online transactions" — that would double-filter and give a much smaller number. Only use idBranch for branch-specific or channel-comparison queries.
""",
    'MonthlyPerformanceSummary': """
**⚠️ CRITICAL COLUMN NAMES:**
- Revenue: `total_monthly_revenue` (**NOT** `total_revenue`, `monthly_revenue_sar`, or `revenue`)
- Visits: `monthly_visits` (**NOT** `total_visits` or `visits`)
- Orders: `total_monthly_orders` (**NOT** `total_orders`)
- Customers: `monthly_customers` (**NOT** `unique_customers` or `total_customers`)
- Time filter: `WHERE year = 2024 AND month = 3` (integers, NOT date functions)
- Channel: `idBranch = -1` (online), `idBranch > 0` (in-store), omit for all channels
- Each row = one branch + one month — use `SUM()` to aggregate across branches
""",
    'CustomerSummary': """
**⚠️ CRITICAL COLUMN NAMES:**
- Registration date: `registration_date` (**NOT** `date`, `created_at`, `join_date`, or `signup_date`)
- Last visit: `last_visit_date` (**NOT** `last_activity` or `last_seen`)
- Segment ID: `loyalty_segment_id` — values: 'superFan', 'loyalCustomer', 'regularCustomer', 'newCustomer', 'lostCustomer', 'potentialCustomer'
- Segment name: `customer_segment` — values: 'Super Fan', 'Loyal Customer', 'Regular Customer', 'New Customer', 'Lost Customer', 'Potential Customer', 'Birthday Present!'
**⚠️ COUNTING PATTERNS:**
- **NO** `new_registrations` or `signups` column exists
- "How many customers registered?" → `SELECT COUNT(*) FROM CustomerSummary WHERE registration_date >= '{{date}}' AND idMerchant = {{merchant_id}}`
- "How many new customers?" → `SELECT COUNT(*) FROM CustomerSummary WHERE registration_date >= '{{date}}' AND idMerchant = {{merchant_id}}`
- ALWAYS include a date range in WHERE — never scan the entire table
- Prefer LoyaltyProgramSummary for segment counts (faster, pre-aggregated)
""",
    'LoyaltyProgramSummary': """
**⚠️ NOTES:**
- For overall merchant totals: `WHERE loyalty_segment_id = 'ALL'`
- For per-segment breakdown: `WHERE loyalty_segment_id != 'ALL'` (EXCLUDE the ALL summary row)
- Segment IDs: 'superFan', 'loyalCustomer', 'regularCustomer', 'newCustomer', 'lostCustomer', 'potentialCustomer', 'birthday', 'ALL'
- `active_members` = count of customers in each segment
- `total_loyalty_visits` = program visits (NOT redemptions)
- All metrics are LIFETIME totals — no date filtering available
- **NO** `total_superfans` or `total_members_count` columns — use `active_members` with segment filter
""",
    'PickupOrderSummary': """
**⚠️ NOTES:**
- Order statuses: 4=done, 5=rejected, 6=returned, 7=timeout
- Pending statuses (1,2,3) excluded from this table
- **ALL-TIME data — NO date columns exist, cannot filter by date**
- If user asks for orders "last month" or any time period → explain this is all-time data and show the overall breakdown instead
- `total_orders_merchant` = total across all statuses for the merchant
""",
    'CampaignSummary': """
**⚠️ CRITICAL COLUMN NAMES:**
- Campaign name: `campaign_title` (**NOT** `campaign_name` or `name`)
- Coupons issued: `total_coupons_issued` (**NOT** `sent_count` or `issued_count`)
- Coupons redeemed: `coupons_used` (**NOT** `redeemed_count` or `redemptions`)
- Redemption rate: `redemption_rate` (pre-calculated percentage — use directly, no need to compute)
- Campaign revenue: `revenue_generated` (**NOT** `total_revenue` or `campaign_revenue`)
- Campaign ROI: `campaign_roi` (pre-calculated)
- Campaign types: 5=Gift, 7=Loyalty Reward, 8=Gift Card
- **IMPORTANT:** When asked about "campaign rates", "campaign performance", or "redemption rates",
  ALWAYS include `campaign_title` in GROUP BY to show per-campaign breakdown.
  Do NOT use AVG(redemption_rate) — show each campaign's individual redemption_rate.
""",
    'MerchantSummary': """
**⚠️ NOTES:**
- ONE row per merchant — all metrics are lifetime totals. No date filtering.
""",
    'GeographicPerformanceSummary': """
**⚠️ NOTES:**
- ONE row per branch — lifetime totals. `idBranch = -1` = online channel. No date filtering.
""",
    'PaymentAnalyticsSummary': """
**⚠️ CRITICAL COLUMN NAMES:**
- Revenue column: `total_amount` (**NOT** `total_revenue` or `revenue`)
- Share column: `method_share` (percentage of merchant's total)
- Group by: `payment_method_id`, `channel` (NOT `payment_method_name` which may be NULL)
- No date filtering available — lifetime data only
- IMPORTANT: `payment_method_name` may be NULL for some merchants. Always GROUP BY `payment_method_id` to ensure data is returned.
""",
    'POSComparisonSummary': """
**⚠️ NOTES:**
- ONE row per merchant — comparison of loyalty vs POS data.
""",
}


# ── Load few-shot examples from YAML semantic model ──
from agent.semantic_model import get_semantic_model as _get_semantic_model
_TABLE_EXAMPLES = _get_semantic_model().get_few_shot_examples()


def _create_query_legacy(state: State) -> dict:
    """[LEGACY] Creates a SQL query via raw LLM SQL generation.

    This is the original approach — the LLM writes raw SQL against the CREATE TABLE DDL.
    Kept as a fallback for the new structured output approach.
    """
    logging.info("[create_query] PATH=legacy_fallback")
    logging.info("--- [LEGACY] Creating SQL Query via raw LLM ---")

    question = state["confirmed_meaning"]
    table_name = state["selected_table"]
    table_schema = state["table_schema"]
    merchant_id = state["merchant_id"]
    history = state.get("history", [])

    # Get previous query context for consistency in follow-ups
    previous_query_columns = state.get("previous_query_columns", "")
    previous_query_metric = state.get("previous_query_metric", "")

    # Read from state (set by data_pipeline) for consistency with main agent's date
    current_date = state.get("current_date")
    current_day_name = state.get("current_day_name")
    if not current_date:
        from agent.config import get_merchant_now
        _now = get_merchant_now()
        current_date = _now.strftime("%Y-%m-%d")
        current_day_name = _now.strftime("%A")

    prompt = ChatPromptTemplate.from_template(
        """You are an expert MySQL analyst. Write a SQL query for the Bonat Analytics Database.

## Security
Every query MUST include `WHERE idMerchant = {merchant_id}`.

## Table: `{table_name}`

```sql
{table_schema}
```

{table_warnings}

{table_examples}

## Query Rules
1. **Never `SELECT *`** — only select columns needed to answer the question.
2. **Only select what was asked:** "total orders" → order count only, NOT revenue. "total visits" → visits only.
3. For broad questions ("tell me about..."), use aggregates (`SUM`, `COUNT`, `AVG`) — do not return raw rows.
4. Write exactly ONE `SELECT` statement (MySQL ignores subsequent statements).
5. Pre-aggregated columns (`total_*`, `*_count`) are already computed — use `SUM()` to total across groups, never `COUNT()` on them.
6. Enclose identifiers in backticks.
7. **Quantity vs Revenue:** Use `SUM(order_count)` or `COUNT(*)` for counts, `SUM(total_revenue)` for money. Never alias revenue as "quantity" or "count".

## Date Context
Today: {current_date} ({current_day_name})
**NEVER use CURDATE(), NOW(), or CURRENT_DATE** — they return wrong timezone. Always use literal dates:
- "today" = '{current_date}'
- "yesterday" = DATE_SUB('{current_date}', INTERVAL 1 DAY)
- "last 7 days" = 7 days counting back from today (includes today): `>= DATE_SUB('{current_date}', INTERVAL 7 DAY)`
  Example: if today is Wed Feb 11, range = Feb 5 → Feb 11
- "last week" = the PREVIOUS full Monday-to-Sunday week (NOT the same as "last 7 days"):
  Example: if today is Wed Feb 11, range = Mon Feb 3 → Sun Feb 9
- "last month" = full previous calendar month: if today is 2026-02-11, last month = '2026-01-01' to '2026-01-31'
- "this month" = '{current_date}' month start to '{current_date}'
- "this week" = most recent Monday to '{current_date}'

{previous_query_context}

## Question
{question}

Return ONLY the raw SQL query. No explanation.

SQL Query:
"""
    )

    # Build previous query context if available
    previous_query_context = ""
    if previous_query_metric and table_name == state.get("selected_table"):
        previous_query_context = f"""**Query Consistency:** Previous query used column `{previous_query_metric}`. For follow-ups about the same metric, use the SAME column for consistency."""

    # Get table-specific column warnings and few-shot examples
    table_warnings = _TABLE_COLUMN_WARNINGS.get(table_name, "")
    table_examples = _TABLE_EXAMPLES.get(table_name, "")

    chain = prompt | get_llm() | StrOutputParser()
    query = chain.invoke({
        "question": question,
        "table_name": table_name,
        "table_schema": table_schema,
        "table_warnings": table_warnings,
        "table_examples": table_examples,
        "merchant_id": merchant_id,
        "previous_query_context": previous_query_context,
        "current_date": current_date,
        "current_day_name": current_day_name
    })

    # ⚠️ SAFETY: Replace date functions with literal dates (LLM sometimes ignores prompt)
    query = _replace_date_functions(query, current_date)

    # ⚠️ SAFETY CHECK: Validate query columns against actual table schema
    invalid_columns = _validate_query_columns(query, table_schema, table_name)

    if invalid_columns:
        logging.warning(f"⚠️ Invalid columns detected: {invalid_columns} in '{table_name}' — attempting auto-correction")

        # Try to auto-correct common hallucinations before failing
        corrected = _auto_correct_columns(query, invalid_columns, table_name)
        if corrected:
            still_invalid = _validate_query_columns(corrected, table_schema, table_name)
            if not still_invalid:
                logging.info(f"✅ Auto-corrected query columns successfully")
                query = corrected
                invalid_columns = []  # All fixed
            else:
                logging.warning(f"Auto-correction partial — still invalid: {still_invalid}")
                invalid_columns = still_invalid

        if invalid_columns:
            logging.error(f"⚠️ QUERY GENERATION ERROR: Query references non-existent columns {invalid_columns} in table '{table_name}'")
            user_message = _get_user_friendly_error(invalid_columns, table_name)
            return {
                "generated_query": query,
                "error_message": user_message
            }

    logging.info(f"Generated query: {query}")

    # Extract the primary metric column used in this query for consistency tracking
    extracted_metric = _extract_primary_metric(query, table_name)
    if extracted_metric:
        logging.info(f"Extracted primary metric for consistency: {extracted_metric}")

    return {
        "generated_query": query,
        "previous_query_metric": extracted_metric,
        "previous_query_columns": query  # Store full query for reference
    }


# ── Load column corrections from YAML semantic model ──
_COLUMN_CORRECTIONS = _get_semantic_model().get_column_corrections()


def _replace_date_functions(query: str, current_date: str) -> str:
    """Replace MySQL date functions with literal dates to ensure correct timezone.

    The LLM sometimes generates CURDATE()/NOW() despite explicit prompt instructions
    not to. These functions return UTC time on the server, not Asia/Riyadh.
    This deterministic post-processing catches and fixes it.
    """
    original = query
    query = re.sub(r'\bCURDATE\(\)', f"'{current_date}'", query, flags=re.IGNORECASE)
    query = re.sub(r'\bCURRENT_DATE\(\)', f"'{current_date}'", query, flags=re.IGNORECASE)
    query = re.sub(r'\bCURRENT_DATE\b', f"'{current_date}'", query, flags=re.IGNORECASE)
    query = re.sub(r'\bNOW\(\)', f"'{current_date}'", query, flags=re.IGNORECASE)
    if query != original:
        logging.info(f"Replaced date functions with literal '{current_date}'")
    return query


def _auto_correct_columns(query: str, invalid_columns: list, table_name: str) -> str | None:
    """
    Try to fix common column name hallucinations by substituting correct names.
    Returns the corrected query, or None if no corrections could be made.
    """
    corrections = _COLUMN_CORRECTIONS.get(table_name, {})
    if not corrections:
        return None

    corrected_query = query
    any_corrected = False

    for col in invalid_columns:
        col_lower = col.lower()
        if col_lower in corrections:
            right = corrections[col_lower]
            # Replace backtick-quoted references
            corrected_query = re.sub(
                rf'`{re.escape(col)}`', f'`{right}`',
                corrected_query, flags=re.IGNORECASE
            )
            # Replace unquoted references (word-boundary safe)
            corrected_query = re.sub(
                rf'\b{re.escape(col)}\b', right,
                corrected_query, flags=re.IGNORECASE
            )
            any_corrected = True
            logging.info(f"Auto-corrected column: `{col}` → `{right}` in {table_name}")

    return corrected_query if any_corrected else None


def _extract_primary_metric(query: str, table_name: str) -> str:
    """
    Extract the primary metric column used in a query for consistency tracking.
    This helps ensure follow-up questions use the same columns.
    """
    query_lower = query.lower()

    # Common metric columns to track by table
    metric_patterns = {
        "DailyPerformanceSummary": [
            (r'\bunique_customers\b', 'unique_customers'),
            (r'\bdaily_visits\b', 'daily_visits'),
            (r'\btotal_revenue\b', 'total_revenue'),
            (r'\btotal_orders\b', 'total_orders'),
            (r'\bpoints_awarded\b', 'points_awarded'),
        ],
        "CustomerSummary": [
            (r'\btotal_visits\b', 'total_visits'),
            (r'\btotal_revenue\b', 'total_revenue'),
            (r'\btotal_orders\b', 'total_orders'),
            (r'\btransaction_count\b', 'transaction_count'),
        ],
        "MonthlyPerformanceSummary": [
            (r'\bmonthly_visits\b', 'monthly_visits'),
            (r'\bunique_customers\b', 'unique_customers'),
            (r'\btotal_monthly_revenue\b', 'total_monthly_revenue'),
            (r'\btotal_orders\b', 'total_orders'),
        ],
    }

    patterns = metric_patterns.get(table_name, [])

    for pattern, metric_name in patterns:
        if re.search(pattern, query_lower):
            return metric_name

    return ""


def _extract_schema_columns(table_schema: str) -> set:
    """
    Extract column names from a CREATE TABLE statement.

    Args:
        table_schema: The CREATE TABLE statement from MySQL

    Returns:
        Set of column names (lowercase for case-insensitive matching)
    """
    columns = set()

    # Match column definitions: `column_name` type...
    # Pattern matches backtick-quoted column names at the start of lines
    column_pattern = r'^\s*`([^`]+)`\s+\w+'

    for line in table_schema.split('\n'):
        match = re.match(column_pattern, line)
        if match:
            columns.add(match.group(1).lower())

    return columns


def _extract_query_columns(query: str) -> set:
    """
    Extract column references from a SQL query.

    Args:
        query: The SQL query string

    Returns:
        Set of column names referenced in the query (lowercase)
    """
    columns = set()

    # Clean the query - remove markdown code blocks if present
    query_clean = re.sub(r'```sql\s*', '', query, flags=re.IGNORECASE)
    query_clean = re.sub(r'```\s*', '', query_clean)
    query_clean = query_clean.strip()

    # Remove string literals to avoid false matches
    query_clean = re.sub(r"'[^']*'", '', query_clean)
    query_clean = re.sub(r'"[^"]*"', '', query_clean)

    # Only extract backtick-quoted identifiers - these are the actual column/table names
    # This is the most reliable method as MySQL queries use backticks for identifiers
    backtick_pattern = r'`([^`]+)`'
    for match in re.finditer(backtick_pattern, query_clean):
        col = match.group(1).lower()
        columns.add(col)

    # Also extract unquoted column references from SQL clauses and aggregate functions
    # This catches cases like SUM(total_revenue) without backticks
    # CRITICAL: \b word boundaries prevent matching keywords INSIDE identifiers
    # e.g., OR inside "PerformanceSummary", SUM inside "Summary", AVG inside "avg_loyalty_score"
    sql_keyword_pattern = r'\b(?:SELECT|WHERE|AND|OR|GROUP\s+BY|ORDER\s+BY|SUM|COUNT|AVG|MAX|MIN|HAVING)\b\s*\(?\s*`?(\w+)`?'
    for match in re.finditer(sql_keyword_pattern, query_clean, re.IGNORECASE):
        col = match.group(1).lower()
        if col not in _SQL_KEYWORDS:
            columns.add(col)

    return columns


def _validate_query_columns(query: str, table_schema: str, table_name: str) -> list:
    """
    Validate that all columns referenced in the query exist in the table schema.

    Args:
        query: The generated SQL query
        table_schema: The CREATE TABLE statement
        table_name: Name of the table being queried

    Returns:
        List of invalid column names found in the query (empty if all valid)
    """
    schema_columns = _extract_schema_columns(table_schema)
    query_columns = _extract_query_columns(query)

    # Filter out the table name itself from query columns
    query_columns.discard(table_name.lower())

    # Find columns in query that don't exist in schema
    invalid = [col for col in query_columns if col not in schema_columns]

    # Log for debugging
    if invalid:
        logging.warning(f"Schema columns for {table_name}: {schema_columns}")
        logging.warning(f"Query columns extracted: {query_columns}")
        logging.warning(f"Invalid columns found: {invalid}")

    return invalid


def _get_user_friendly_error(invalid_columns: list, table_name: str) -> str:
    """
    Generate a user-friendly error message based on the invalid columns detected.

    Args:
        invalid_columns: List of column names that don't exist
        table_name: The table being queried

    Returns:
        User-friendly error message that guides the agent toward correct behavior
    """
    # Table-specific suggestions — guide the agent to what it CAN do
    _TABLE_SUGGESTIONS = {
        'PickupOrderSummary': (
            "PickupOrderSummary contains ALL-TIME order data only — it cannot be "
            "filtered by date. Show the overall order breakdown by status instead. "
            "Explain to the user that pickup order data is available as an all-time summary."
        ),
        'POSComparisonSummary': (
            "POSComparisonSummary is merchant-level only — it does NOT have branch-level "
            "or product-level breakdown. For branch data, try rephrasing the question to ask "
            "about GeographicPerformanceSummary. Explain the limitation to the user."
        ),
        'MerchantSummary': (
            "MerchantSummary contains lifetime totals only (one row per merchant). "
            "It cannot be filtered by date. For time-based data, rephrase the question "
            "to use daily or monthly performance data."
        ),
    }

    if table_name in _TABLE_SUGGESTIONS:
        return _TABLE_SUGGESTIONS[table_name]

    # Check for common hallucination patterns
    date_columns = {'performance_date', 'date', 'order_date', 'transaction_date', 'created_at'}
    segment_columns = {'customer_segment', 'segment'}

    invalid_set = set(col.lower() for col in invalid_columns)

    # Date filtering on non-time-series table
    if invalid_set & date_columns:
        return (
            f"The {table_name} table contains lifetime totals and cannot be filtered by date. "
            "For time-based analysis, try rephrasing to ask about daily or monthly performance "
            "(e.g., 'Show me revenue for last month' or 'How many visits this week')."
        )

    # Segment column on wrong table
    if invalid_set & segment_columns:
        return (
            "To get customer segment information, try rephrasing the question to ask about "
            "customer segments (e.g., 'How many customers are in each segment?')."
        )

    # Generic error — suggest retrying with different phrasing, never say "not tracked"
    return (
        f"The columns ({', '.join(invalid_columns)}) don't exist in the {table_name} table. "
        f"Try rephrasing the question — the data may be available under different column names. "
        f"You can ask about: revenue, visits, orders, customer counts, or loyalty segments."
    )
