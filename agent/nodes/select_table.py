import logging
import re
from agent.config import get_llm, mysql_schemas as schemas
from .types import State


# ═══════════════════════════════════════════════════════════════════════════════
# Intent Category → Table Mapping (for structured tool arguments)
# ═══════════════════════════════════════════════════════════════════════════════
# When the main agent calls query_db with intent_category, it routes directly
# to the correct table — immune to reformulation drift that breaks regex routing.

# ── Load intent category map from YAML semantic model ──
from agent.semantic_model import get_semantic_model as _get_semantic_model
INTENT_CATEGORY_TABLE_MAP = _get_semantic_model().get_intent_category_map()


def _deterministic_route(question: str) -> str | None:
    """
    Pattern-match the question to a table WITHOUT calling the LLM.
    Returns a table name for high-confidence matches, or None to fall through to the LLM.
    """
    q = question.lower().strip()

    # ── Pre-guard: Arabic segment COUNT questions → LoyaltyProgramSummary ──
    # Must fire BEFORE time-query detection, because the main agent sometimes
    # reformulates Arabic questions with explicit dates, which would trigger
    # time_patterns and mis-route to CustomerSummary.
    arabic_count_guard = [
        r'كم\s+(?:عدد\s+)?(?:العملاء|عملاء)\s+(?:الجدد|جدد|المفقودين|مفقودين|المخلصين|مخلصين)',
        r'كم\s+عدد\s+العملاء\s+الجدد',
    ]
    for pat in arabic_count_guard:
        if re.search(pat, q):
            return 'LoyaltyProgramSummary'

    # ── Pre-guard: Branch comparison questions → GeographicPerformanceSummary ──
    # "Which branch has the most visits/revenue" is a LIFETIME comparison.
    # Must fire BEFORE time_patterns, because the main agent may add dates
    # via intent_category=daily_metrics, misrouting to DailyPerformanceSummary.
    branch_comparison_guard = [
        r'\bwhich\s+branch\b',
        r'\bbest\s+(?:performing\s+)?branch\b',
        r'\bworst\s+(?:performing\s+)?branch\b',
        r'\btop\s+branch\b',
        r'أفضل\s+فرع',
        r'أسوأ\s+فرع',
    ]
    for pat in branch_comparison_guard:
        if re.search(pat, q):
            return 'GeographicPerformanceSummary'

    # ── Detect time-based queries ──
    time_patterns = re.compile(
        r'\b(last\s+\d+\s+days?|last\s+\d+\s+months?|last\s+week|last\s+month|last\s+year'
        r'|this\s+week|this\s+month|this\s+year|today|yesterday|since\s+\d{4}'
        r'|recent|per\s+day|per\s+month|daily|monthly|weekly|year[\s-]over[\s-]year'
        r'|\d{4}-\d{2}-\d{2}'
        r'|(?:in|for|during|from)\s+(?:january|february|march|april|may|june'
        r'|july|august|september|october|november|december)'
        r'|(?:january|february|march|april|may|june'
        r'|july|august|september|october|november|december)\s+\d{4}'
        r'|(?:joined|registered|visited)\s+(?:in|last|this)'
        r'|خلال|آخر|الأسبوع|الشهر|اليوم|أمس'
        r'|يناير|فبراير|مارس|أبريل|مايو|يونيو'
        r'|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\b'
    )
    is_time_query = bool(time_patterns.search(q))

    if is_time_query:
        # ── Route time queries to the correct time-series table instead of LLM ──

        # Pickup orders with time → PickupOrderSummary (ALL-TIME only, but still the right table)
        if re.search(r'\b(pickup\s+orders?|order\s+status|rejected\s+orders?|accepted\s+orders?)\b', q):
            return 'PickupOrderSummary'

        # Monthly aggregation keywords → MonthlyPerformanceSummary
        if re.search(r'\b(monthly|month[\s-]over[\s-]month|year[\s-]over[\s-]year|per\s+month)\b'
                      r'|(?:شهري)', q):
            return 'MonthlyPerformanceSummary'

        # Segment-qualified visits/customer queries → CustomerSummary
        # "loyal customers visited last month" needs CustomerSummary (filter by segment + last_visit_date)
        # Must fire BEFORE generic visit keyword match below
        if re.search(r'\b(?:loyal|new|lost|super\s*fan|regular|potential)\s+customers?\s+(?:\w+\s+)*visited\b'
                      r'|\bvisited\b.*\b(?:loyal|new|lost|super\s*fan|regular|potential)\s+customers?\b', q):
            return 'CustomerSummary'

        # Visit keywords (English + Arabic) → DailyPerformanceSummary
        if re.search(r'\bvisit(?:s|ed)?\b|زيارات|الزيارات', q):
            return 'DailyPerformanceSummary'

        # Revenue keywords (English + Arabic) → DailyPerformanceSummary
        if re.search(r'\brevenue\b|إيرادات|مبيعات|sales', q):
            return 'DailyPerformanceSummary'

        # Daily performance / general time-series metrics → DailyPerformanceSummary
        if re.search(r'\b(daily|performance|transactions?|orders?)\b', q):
            return 'DailyPerformanceSummary'

        # Customer registration with time → CustomerSummary
        # IMPORTANT: requires a registration verb (registered/joined/signed/visited).
        # Bare "new customers" without a verb means segment count → LoyaltyProgramSummary
        # (handled by count_patterns below). Arabic patterns caught by pre-guard above.
        if re.search(r'\bcustomers?\s+(?:\w+\s+)*(?:registered|joined|signed\s+up|visited)\b'
                      r'|(?:registered|joined|signed\s+up|visited)\s+(?:new\s+)?customers?\b', q):
            return 'CustomerSummary'

        # Campaign with time → CampaignSummary
        if re.search(r'\bcampaign\b|حملة|حملات', q):
            return 'CampaignSummary'

        # Fallback for unrecognized time queries → let LLM decide
        return None

    # ── Segment keywords (Arabic + English)
    segment_keywords = [
        'super fan', 'superfan', 'loyal customer', 'loyal segment',
        'new customer', 'lost customer', 'regular customer', 'potential customer',
        'birthday customer', 'birthday present',
        'سوبر فان', 'عملاء مخلصين', 'عملاء جدد', 'عملاء مفقودين',
        # Arabic with definite article (ال prefix)
        'العملاء الجدد', 'العملاء المفقودين', 'العملاء المخلصين',
        # Birthday in Arabic
        'عيد ميلاد', 'أعياد ميلاد',
    ]

    # ── Guard: branch-specific or individual-detail queries need CustomerSummary, not LoyaltyProgramSummary
    needs_individual_data = bool(re.search(
        r'\b(?:branch|فرع|riyadh|jeddah|الرياض|جدة)\b', q
    ))

    # ── Guard: campaign-related questions should not match loyalty keywords
    is_campaign_question = bool(re.search(r'\bcampaign\b|حملة|حملات', q))

    # ── 1. Segment COUNTING → LoyaltyProgramSummary (only when no branch filter needed)
    count_patterns = [
        r'how many\b.*\b(?:' + '|'.join(re.escape(s) for s in segment_keywords) + r')',
        r'(?:' + '|'.join(re.escape(s) for s in segment_keywords) + r').*\bhow many\b',
        r'\b(?:number|count|total)\b.*\b(?:' + '|'.join(re.escape(s) for s in segment_keywords) + r')',
        r'كم\s+(?:عدد\s+)?(?:عميل|عملاء|العملاء).*(?:سوبر|مخلص|جدد|الجدد|مفقود|المفقودين|ميلاد)',
        r'(?:سوبر|مخلص|جدد|الجدد|مفقود|المفقودين|ميلاد).*كم',
        r'كم\s+عدد\s+العملاء\s+الجدد',  # "how many new customers" with definite articles
        r'\bbirthday\b.*\bcustomer',  # "birthday customers"
        r'\bcustomer.*\bbirthday\b',  # "customers with birthdays"
        r'\bsegment\s+breakdown\b',
        r'\bbreakdown\s+by\s+segment\b',
        r'\bcustomers?\s+(?:are\s+)?in\s+each\s+(?:loyalty\s+)?segment\b',
        r'\bhow\s+many\s+customers?\s+(?:are\s+)?(?:in\s+)?each\s+(?:loyalty\s+)?segment\b',
        r'\bsegment\s+distribution\b',
        r'\bsegment\s+count\b',
    ]
    if not needs_individual_data:
        for pat in count_patterns:
            if re.search(pat, q):
                return 'LoyaltyProgramSummary'

    # ── 2. Loyalty metrics → LoyaltyProgramSummary (skip if campaign context)
    loyalty_keywords = [
        'loyalty score', 'points redemption', 'rewards redemption',
        'gifts redemption', 'coupons redemption', 'active members',
        'engagement rate',
        'نقاط', 'مكافآت', 'هدايا', 'كوبونات',
    ]
    # "redemption rate" only matches loyalty when NOT a campaign question
    if not is_campaign_question:
        loyalty_keywords.append('redemption rate')

    for kw in loyalty_keywords:
        if kw in q:
            return 'LoyaltyProgramSummary'

    # ── 3. High-level totals (no segment qualifier) → MerchantSummary
    has_segment = any(s in q for s in segment_keywords) or re.search(r'\bsegment\b', q)

    # ── 3a. Online transactions → DailyPerformanceSummary (NOT MerchantSummary)
    # "online transactions" = DailyPerformanceSummary.total_orders (coupon redemptions)
    if re.search(r'\bonline\s+transactions?\b|\bcoupon\s+(?:orders?|transactions?)\b', q):
        return 'DailyPerformanceSummary'

    # ── 3b. Branch-level visit/revenue aggregation → DailyPerformanceSummary
    has_branch_context = bool(re.search(
        r'\bacross\s+(?:all\s+)?branches\b|\bby\s+branch\b|\bper\s+branch\b|\beach\s+branch\b', q
    ))
    if has_branch_context and re.search(r'\bvisit', q):
        return 'DailyPerformanceSummary'

    merchant_patterns = [
        r'\btotal\s+customers?\b',
        r'\bhow\s+many\s+customers?\s+do\s+i\s+have\b',
        r'\bhow\s+many\s+customers?\s+(?:are\s+there|do\s+we\s+have)\b',
        r'\btotal\s+revenue\b',
        r'\btotal\s+visits?\b',
        r'\btotal\s+branches\b',
        r'\bhow\s+many\s+branches\b',
        r'كم\s+عدد\s+العملاء',
        r'كم\s+(?:عميل|عملاء)\s*(?:عندي|لدي|لديك)?$',
        r'كم\s+عدد\s+الفروع',
    ]
    has_payment_context = bool(re.search(r'\bpayment\s+methods?\b|طرق?\s+الدفع', q))
    if not has_segment and not has_branch_context and not has_payment_context:
        for pat in merchant_patterns:
            if re.search(pat, q):
                return 'MerchantSummary'

    # ── 4. Orders → PickupOrderSummary
    order_patterns = [
        r'\btotal\s+orders?\b',
        r'\bhow\s+many\s+orders?\b',
        r'\border\s+status\b',
        r'\brejected\s+orders?\b',
        r'\baccepted\s+orders?\b',
        r'\breturned\s+orders?\b',
        r'\border\s+breakdown\b',
        r'\btimeout\s+orders?\b',
        r'\bbreakdown\b.*\borders\b',  # "breakdown of orders" / "breakdown حق الـ orders"
        r'\borders\b.*\bbreakdown\b',  # "orders breakdown"
        r'طلبات|الطلبات',              # Arabic for "orders"
    ]
    for pat in order_patterns:
        if re.search(pat, q):
            return 'PickupOrderSummary'

    # ── 5. Campaigns → CampaignSummary
    if is_campaign_question:
        return 'CampaignSummary'

    # ── 6. Branches → GeographicPerformanceSummary
    branch_patterns = [
        r'\bwhich\s+branch\b',
        r'\bbranch\s+comparison\b',
        r'\bbest\s+(?:performing\s+)?branch\b',
        r'\bworst\s+(?:performing\s+)?branch\b',
        r'\bbranch\s+(?:performance|revenue|breakdown)\b',
        r'\bcompare\s+branches\b',
        r'أفضل\s+فرع',
        r'مقارنة\s+(?:الفروع|فروع)',
    ]
    for pat in branch_patterns:
        if re.search(pat, q):
            return 'GeographicPerformanceSummary'

    # ── 7. Payment methods → PaymentAnalyticsSummary
    # (renumbered after removing ProductPerformanceSummary)
    payment_patterns = [
        r'\bpayment\s+methods?\b',
        r'\bcash\s+vs\s+card\b',
        r'\bpayment\s+breakdown\b',
        r'\bpayment\s+(?:type|split|distribution)\b',
        r'طرق?\s+الدفع',
        r'نقد.*بطاقة|بطاقة.*نقد',
    ]
    for pat in payment_patterns:
        if re.search(pat, q):
            return 'PaymentAnalyticsSummary'

    # ── 8. Revenue by payment method → PaymentAnalyticsSummary
    if re.search(r'\brevenue\b.*\bpayment\b|\bpayment\b.*\brevenue\b', q):
        return 'PaymentAnalyticsSummary'

    # ── 9. Product/item keywords → POSComparisonSummary
    product_patterns = [
        r'\b(?:latte|coffee|product|item|menu)\b.*\b(?:sold|sales?|sell(?:ing)?)\b',
        r'\b(?:sold|sales?|sell(?:ing)?)\b.*\b(?:latte|coffee|product|item|menu)\b',
        r'\bbest[- ]sell(?:ing|er)\b',   # "best selling" or "best-selling"
        r'\btop\s+(?:selling|products?|items?)\b',  # "top products", "top product", "top selling"
        r'\bbest[- ](?:selling\s+)?products?\b',  # "best product", "best-selling products"
        r'\bhow\s+many\s+\w+\s+(?:did\s+we\s+sell|sold|were\s+sold)\b',
        r'أفضل\s+منتج',               # Arabic: best product
        r'منتج',                       # Arabic: product (generic)
        r'المنتجات',                   # Arabic: the products
        r'أكثر\s+منتج',               # Arabic: most product (top product)
    ]
    for pat in product_patterns:
        if re.search(pat, q):
            return 'POSComparisonSummary'

    # No confident match → fall through to LLM
    return None


def select_table(state: State) -> dict:
    """Selects the most relevant table from the database schema to answer the user's question."""
    logging.info("--- Selecting Relevant Table ---")
    question = state["user_prompt"]
    confirmed = state.get("confirmed_meaning") or ""
    history = state.get("history", [])

    # ── Priority 0: Arabic segment COUNT guard on ORIGINAL question ──
    # Must fire BEFORE confirmed_meaning routing, because the main agent
    # reformulates Arabic into English + adds explicit dates → confirmed_meaning
    # triggers time_patterns → mis-routes to CustomerSummary.
    _arabic_segment_count_pats = [
        r'كم\s+(?:عدد\s+)?(?:العملاء|عملاء)\s+(?:الجدد|جدد|المفقودين|مفقودين|المخلصين|مخلصين)',
        r'كم\s+عدد\s+العملاء\s+الجدد',
    ]
    q_orig = question.lower().strip()
    for pat in _arabic_segment_count_pats:
        if re.search(pat, q_orig) and 'LoyaltyProgramSummary' in schemas:
            logging.info(f"Arabic count guard (select_table): '{question[:60]}' → LoyaltyProgramSummary")
            return {"selected_table": "LoyaltyProgramSummary", "table_schema": schemas["LoyaltyProgramSummary"]}

    # ── Priority 1: Deterministic regex pre-router (instant, zero LLM cost) ──
    # Highest confidence for well-known patterns — catches time queries, segments, etc.
    # Try confirmed_meaning first (cleaner phrasing), then raw user_prompt
    deterministic_table = _deterministic_route(confirmed) if confirmed else None
    if deterministic_table is None:
        deterministic_table = _deterministic_route(question)

    if deterministic_table and deterministic_table in schemas:
        logging.info(f"Deterministic route: '{(confirmed or question)[:80]}' → {deterministic_table}")
        return {"selected_table": deterministic_table, "table_schema": schemas[deterministic_table]}

    # ═══════════════════════════════════════════════════════════════════════
    # Collect candidates from Layers 2-5 for top-2 selection (self-correction)
    # Each candidate: (table_name, score, source_label)
    # Score range: 0.0 - 1.0 (higher = more confident)
    # ═══════════════════════════════════════════════════════════════════════
    candidates: list[tuple[str, float, str]] = []

    # ── Layer 2: Semantic router (embedding similarity) ──
    from agent.nodes.semantic_router import get_semantic_router
    try:
        router = get_semantic_router()
        semantic_table, confidence = router.route(question)
        if semantic_table is None and confirmed:
            semantic_table, confidence = router.route(confirmed)
        if semantic_table and semantic_table in schemas:
            candidates.append((semantic_table, confidence, "semantic"))
    except Exception as e:
        logging.warning(f"Semantic router failed: {e}")

    # ── Layer 3: Example store — Function RAG ──
    try:
        from agent.example_store import get_example_store
        example_store = get_example_store()
        similar = example_store.find_similar(confirmed or question, top_k=2, min_score=0.85)
        for ex in similar:
            if ex["table"] in schemas:
                candidates.append((ex["table"], ex["score"], "example_store"))
    except Exception as e:
        logging.warning(f"Example store failed: {e}")

    # ── Layer 4: Structured intent_category ──
    intent_category = state.get("intent_category")
    if intent_category and intent_category in INTENT_CATEGORY_TABLE_MAP:
        table = INTENT_CATEGORY_TABLE_MAP[intent_category]
        if table in schemas:
            # intent_category gets a fixed score of 0.80 (moderate confidence)
            candidates.append((table, 0.80, "intent_category"))

    # ── Pick primary + fallback from candidates ──
    if candidates:
        # Sort by score descending
        candidates.sort(key=lambda c: c[1], reverse=True)
        primary_table = candidates[0][0]
        primary_score = candidates[0][1]
        primary_source = candidates[0][2]

        # Find fallback: first candidate with a DIFFERENT table
        fallback_table = None
        fallback_source = None
        for cand_table, cand_score, cand_source in candidates[1:]:
            if cand_table != primary_table:
                fallback_table = cand_table
                fallback_source = cand_source
                break

        # ── Disambiguation: if top-2 tables score within 0.05 and confidence is low ──
        # Flag this for the pipeline so it can include a disambiguation hint
        needs_disambiguation = False
        if fallback_table and primary_score < 0.85:
            # Find fallback score
            for cand_table, cand_score, _ in candidates:
                if cand_table == fallback_table:
                    if abs(primary_score - cand_score) < 0.05:
                        needs_disambiguation = True
                    break

        logging.info(
            f"Candidate route: '{question[:60]}' → {primary_table} "
            f"(score={primary_score:.3f}, source={primary_source})"
            + (f", fallback={fallback_table} ({fallback_source})" if fallback_table else "")
            + (" [AMBIGUOUS]" if needs_disambiguation else "")
        )

        result = {
            "selected_table": primary_table,
            "table_schema": schemas[primary_table],
        }
        if fallback_table:
            result["fallback_table"] = fallback_table
            result["fallback_schema"] = schemas[fallback_table]
        if needs_disambiguation:
            result["disambiguation_hint"] = (
                f"Routing confidence is low — '{primary_table}' and '{fallback_table}' "
                f"scored very close. If the result doesn't look right, the data may "
                f"be in the other table."
            )
        return result

    # ── Layer 5: LLM fallback (expensive, last resort) ──
    previous_table = state.get("selected_table")

    formatted_history = ""
    if history:
        for item in history:
            if isinstance(item, str):
                formatted_history += f"{item}\n"

    if not schemas:
        logging.error("No schemas found. Cannot select a table.")
        return {"selected_table": None, "table_schema": None}

    formatted_schemas = "\n\n".join(schemas.values())

    previous_table_context = ""
    if previous_table:
        previous_table_context = f"""
**Previous table:** `{previous_table}`
- Follow-up question ("what about...", "break that down", pronouns) → prefer `{previous_table}`
- New topic/metric → select fresh based on rules below
"""

    prompt = f"""You are an expert MySQL data analyst. Select the single best table to answer the user's question.

Respond with ONLY the table name. No other text.

## Hard Rules (check FIRST — override everything else)

**A. Customer Segment Counts** ("how many Super Fans?", "segment breakdown"):
→ `LoyaltyProgramSummary` (pre-aggregated, has `total_members` per segment)
→ For individual customer details/lists/averages → `CustomerSummary`

**B. Orders without timeframe** ("total orders", "order status", "rejected orders"):
→ `PickupOrderSummary` (all-time status breakdown)
→ `DailyPerformanceSummary.total_orders` = online coupon transactions (DIFFERENT from pickup orders)

**C. Time-based visits/revenue** ("last 7 days", "this week", "daily"):
→ `DailyPerformanceSummary` (has `performance_date`)
→ Monthly trends → `MonthlyPerformanceSummary`

## Table Routing

| Table | Grain | Time Scope | Use For |
|-------|-------|------------|---------|
| MerchantSummary | 1 row/merchant | Lifetime | "total customers", "total revenue", "how many branches" |
| CustomerSummary | 1 row/customer | Lifetime | Individual details, top customers, demographics, per-customer metrics |
| CampaignSummary | 1 row/campaign | Per campaign | Campaign ROI, redemption rate, campaign performance |
| DailyPerformanceSummary | 1 row/branch/day | Daily time-series | Visits by date, daily revenue, recent activity, time trends |
| MonthlyPerformanceSummary | 1 row/branch/month | Monthly time-series | Monthly trends, year-over-year, seasonal analysis |
| LoyaltyProgramSummary | 1 row/segment | Lifetime | Segment counts, loyalty score, points/rewards/gifts/coupons stats |
| GeographicPerformanceSummary | 1 row/branch | Lifetime | Branch comparison, best/worst branch, location analysis |
| PaymentAnalyticsSummary | 1 row/method/channel | Lifetime | Payment methods, cash vs card |
| PickupOrderSummary | 1 row/status | All-time | Order breakdown by status (done, rejected, returned, timeout) |

**Key constraints:**
- LIFETIME tables cannot answer time-filtered questions ("last month", "this year")
- `DailyPerformanceSummary` does NOT have `customer_segment` — use CustomerSummary for segment-filtered queries
- "new customers" or "lost customers" with time → `CustomerSummary` (filter by `registration_date` or `last_visit_date`)

## Schemas

{formatted_schemas}

## Context

Conversation history:
{formatted_history}

User's question: "{confirmed or question}"
{previous_table_context}
"""

    response = get_llm().invoke(prompt)
    table_name = response.content.strip().replace("`", "").replace("'", "").replace('"', "").strip()

    if table_name not in schemas:
        logging.warning(f"LLM selected a non-existent table: '{table_name}'. Available tables: {list(schemas.keys())}")
        return {"selected_table": None, "table_schema": None}

    table_schema = schemas[table_name]
    return {"selected_table": table_name, "table_schema": table_schema}
