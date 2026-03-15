"""
Proactive Insights Module

Handles generation and delivery of proactive business insights to merchants.
Insights are shown once per day on first chat, combining:
- Business data metrics (via query_db tool)
- Strategic recommendations (via agentic_rag tool)
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def make_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Converts a naive datetime to UTC-aware datetime.
    If already aware, returns as-is.
    If None, returns None.

    This handles legacy data that was stored with datetime.utcnow().
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        # Naive datetime - assume it's UTC and make it aware
        return dt.replace(tzinfo=timezone.utc)

    # Already aware
    return dt


def get_effective_now() -> datetime:
    """
    Gets the current datetime in UTC.

    Returns:
        Current datetime in UTC timezone
    """
    return datetime.now(timezone.utc)


def should_show_proactive_insights(user_data: dict) -> Tuple[bool, Optional[datetime]]:
    """
    Determines if agent should proactively show insights instead of greeting.

    Business Rules:
    1. Only show once per calendar day (check last_insight_date vs today)
    2. User must have logged in before (need data window)
    3. Cap data window at 14 days to avoid overwhelming data

    Args:
        user_data: User document from MongoDB users collection

    Returns:
        Tuple of (should_show: bool, data_since: datetime | None)
        - should_show: True if insights should be shown
        - data_since: Datetime to query data from (None if shouldn't show)
    """
    # Get current time
    now = get_effective_now()
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Convert datetimes to aware (handles legacy naive datetimes)
    last_insight_date = make_aware(user_data.get('last_insight_date'))
    # Use previous_login for data window (last_login is updated on current login)
    previous_login = make_aware(user_data.get('previous_login'))
    last_login = make_aware(user_data.get('last_login'))

    logger.info(f"Insights check for user {user_data.get('user_id')}: now={now}, today_midnight={today_midnight}")
    logger.info(f"  last_insight_date={last_insight_date}, previous_login={previous_login}, last_login={last_login}")

    # Rule 1: Check if insights already shown today (calendar day check)
    insights_already_shown_today = (
        last_insight_date and last_insight_date >= today_midnight
    )

    if insights_already_shown_today:
        logger.info(f"Insights already shown today for user {user_data.get('user_id')} (last_insight_date={last_insight_date} >= today_midnight={today_midnight})")
        return False, None

    # Rule 2: User must have previous login (so we have a data window)
    # Use previous_login if available, otherwise fall back to last_login
    data_reference = previous_login or last_login

    if not data_reference:
        logger.info(f"First-time user {user_data.get('user_id')} - no previous login")
        return False, None  # First-time user, just greet normally

    # Rule 3: Calculate data window (from previous login to now)
    # - Minimum window: 1 day (ensure ETL data exists)
    # - Maximum window: 14 days (avoid overwhelming data)
    data_since = data_reference
    max_window = now - timedelta(days=14)
    min_window = now - timedelta(days=1)

    if data_since < max_window:
        logger.info(f"Capping data window to 14 days for user {user_data.get('user_id')}")
        data_since = max_window
    elif data_since > min_window:
        # Previous login was too recent - use yesterday to ensure ETL data exists
        logger.info(f"Extending data window to 1 day minimum for user {user_data.get('user_id')}")
        data_since = min_window

    logger.info(f"Will show insights for user {user_data.get('user_id')} from {data_since}")
    return True, data_since


def should_offer_monthly_report(user_data: dict) -> Tuple[bool, Optional[str]]:
    """
    Determines if agent should offer monthly report.

    Business Rules:
    1. Only show at END OF MONTH (last 3 days of month OR first 3 days of new month)
    2. Only offer once per month (check last_monthly_report_date)
    3. User must have at least 30 days of data
    4. Don't spam if user dismissed recently (check monthly_report_dismissal_count)
    5. Don't show prompt again if already shown in last 10 minutes (prevents refresh spam)

    Args:
        user_data: User document from MongoDB users collection

    Returns:
        Tuple of (should_offer: bool, reason: str | None)
        - should_offer: True if monthly report should be offered
        - reason: Why we should/shouldn't offer (for logging)
    """
    import calendar

    # Get current time
    now = get_effective_now()
    current_day = now.day
    current_month = now.month
    current_year = now.year

    # Get last day of current month
    _, last_day_of_month = calendar.monthrange(current_year, current_month)

    # Convert datetimes to aware
    last_monthly_report = make_aware(user_data.get('last_monthly_report_date'))
    account_created = make_aware(user_data.get('created_at'))
    monthly_prompt_shown_at = make_aware(user_data.get('monthly_prompt_shown_at'))

    # Rule 0: Check if prompt was shown recently (within 10 minutes) - prevents refresh spam
    # Use REAL time for this check, not simulated time
    real_now = datetime.now(timezone.utc)
    if monthly_prompt_shown_at:
        minutes_since_prompt = (real_now - monthly_prompt_shown_at).total_seconds() / 60
        if 0 < minutes_since_prompt < 10:  # Must be positive and less than 10 minutes
            return False, f"Monthly prompt already shown {minutes_since_prompt:.1f} minutes ago"

    # Rule 1: Only show at END OF MONTH (last 3 days) OR start of new month (first 3 days)
    is_end_of_month = current_day >= (last_day_of_month - 2)  # Last 3 days
    is_start_of_month = current_day <= 3  # First 3 days

    if not (is_end_of_month or is_start_of_month):
        return False, f"Not end/start of month (day {current_day})"

    # Rule 2: Check if report already offered this month
    if last_monthly_report:
        # If we're in first 3 days of month, check if shown last month
        if is_start_of_month:
            # Report should have been shown last month's end, not this month
            if last_monthly_report.month == current_month and last_monthly_report.year == current_year:
                return False, "Monthly report already offered this month"
        else:
            # End of month - check if shown this month
            if last_monthly_report.month == current_month and last_monthly_report.year == current_year:
                return False, "Monthly report already offered this month"

    # Rule 3: User must have at least 30 days of data
    if account_created and (now - account_created).days < 30:
        return False, "Account too new (< 30 days old)"

    # Rule 4: Check dismissal count (anti-spam)
    dismissal_count = user_data.get('monthly_report_dismissal_count', 0)
    if dismissal_count >= 3:
        # If user dismissed 3+ times, only offer once per 3 months
        if last_monthly_report and (now - last_monthly_report).days < 90:
            return False, f"User dismissed {dismissal_count} times, cooling off period"

    logger.info(f"Should offer monthly report to user {user_data.get('user_id')} (end/start of month)")
    return True, "End of month - time for monthly report"


def mark_insights_shown(collections: dict, user_id: str):
    """
    Marks that proactive insights were shown to user today.
    Updates last_insight_date to today's midnight for easy daily comparison.

    Args:
        collections: MongoDB collections dict
        user_id: User identifier
    """
    now = datetime.now(timezone.utc)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    result = collections['users'].update_one(
        {"user_id": user_id},
        {
            "$set": {"last_insight_date": today_midnight},
            "$inc": {"insight_shown_count": 1}
        }
    )

    logger.info(f"Marked insights shown for user {user_id}: {result.modified_count} documents updated")


def mark_monthly_prompt_shown(collections: dict, user_id: str):
    """
    Marks that monthly report PROMPT was shown (not yet accepted/declined).
    This prevents the prompt from showing again on page refresh.

    Args:
        collections: MongoDB collections dict
        user_id: User identifier
    """
    now = datetime.now(timezone.utc)

    result = collections['users'].update_one(
        {"user_id": user_id},
        {"$set": {"monthly_prompt_shown_at": now}}
    )

    logger.info(f"Marked monthly prompt shown for user {user_id}")


def is_awaiting_monthly_response(user_data: dict) -> bool:
    """
    Checks if user was recently shown the monthly report prompt and we're awaiting their response.
    Returns True if prompt was shown within the last 10 minutes (user might be responding).

    Args:
        user_data: User document from MongoDB users collection

    Returns:
        True if we're awaiting response to monthly prompt
    """
    # Use REAL time for this check - we want to know if prompt was shown
    # recently in real time, not simulated time
    now = datetime.now(timezone.utc)
    monthly_prompt_shown_at = make_aware(user_data.get('monthly_prompt_shown_at'))

    logger.info(f"is_awaiting_monthly_response check: monthly_prompt_shown_at={monthly_prompt_shown_at}, now={now}")

    if not monthly_prompt_shown_at:
        logger.info("No monthly_prompt_shown_at found - not awaiting response")
        return False

    minutes_since_prompt = (now - monthly_prompt_shown_at).total_seconds() / 60
    logger.info(f"Minutes since monthly prompt: {minutes_since_prompt:.1f}")

    # If prompt was shown within last 10 minutes, we're awaiting response
    if minutes_since_prompt < 10:
        logger.info(f"User is responding to monthly prompt (shown {minutes_since_prompt:.1f} min ago)")
        return True

    logger.info(f"Monthly prompt too old ({minutes_since_prompt:.1f} min) - not awaiting response")
    return False


def mark_monthly_report_offered(collections: dict, user_id: str, accepted: bool):
    """
    Marks that monthly report was offered to user.

    Args:
        collections: MongoDB collections dict
        user_id: User identifier
        accepted: Whether user accepted the offer
    """
    now = datetime.now(timezone.utc)

    update_fields = {"last_monthly_report_date": now}

    if accepted:
        # Reset dismissal count on acceptance, increment acceptance count
        collections['users'].update_one(
            {"user_id": user_id},
            {
                "$set": {"last_monthly_report_date": now, "monthly_report_dismissal_count": 0},
                "$inc": {"monthly_report_acceptance_count": 1}
            }
        )
        logger.info(f"User {user_id} ACCEPTED monthly report")
    else:
        collections['users'].update_one(
            {"user_id": user_id},
            {
                "$set": update_fields,
                "$inc": {"monthly_report_dismissal_count": 1}
            }
        )
        logger.info(f"User {user_id} DISMISSED monthly report")


async def generate_proactive_insights(
    merchant_id: str,
    data_since: datetime,
    user_email: str
) -> str:
    """
    Generates proactive insights showing recent business data.

    Simplified version: Just shows key metrics, no RAG insights.

    Args:
        merchant_id: Merchant identifier for data isolation
        data_since: Datetime to query data from (not used in simple version)
        user_email: User email for logging

    Returns:
        Formatted markdown string ready to stream to user
    """
    from agent.tools import query_db

    logger.info(f"Generating proactive insights for merchant {merchant_id} ({user_email})")

    # ============================================
    # Business snapshot using separate focused queries
    # ============================================
    # Strategy: Make 3 separate calls to query_db, each focused on ONE metric
    # This ensures each call selects the RIGHT table and gets COMPLETE data

    business_data = ""
    try:
        # Format the time window for queries
        time_window_str = format_time_window(data_since)
        logger.info(f"Fetching business snapshot for time window: {time_window_str} (since {data_since})")

        # Run all 3 queries in parallel using asyncio.to_thread
        # Each query_db.invoke() is synchronous (~4-5s each), so running them
        # concurrently reduces total time from ~14s to ~5s
        logger.info("Fetching visits, segments, and orders data in parallel...")
        visits_data, customers_data, orders_data = await asyncio.gather(
            asyncio.to_thread(query_db.invoke, {
                "user_question": f"Total visits since {data_since.strftime('%Y-%m-%d')}",
                "merchant_id": merchant_id
            }),
            asyncio.to_thread(query_db.invoke, {
                "user_question": "Customer segment distribution showing total members and active members per segment from LoyaltyProgramSummary (exclude the ALL row)",
                "merchant_id": merchant_id
            }),
            asyncio.to_thread(query_db.invoke, {
                "user_question": f"Total daily orders (daily_orders column) since {data_since.strftime('%Y-%m-%d')} from DailyPerformanceSummary table",
                "merchant_id": merchant_id
            }),
        )
        logger.info(f"Visits data retrieved: {len(visits_data)} characters")
        logger.info(f"Customer data retrieved: {len(customers_data)} characters")
        logger.info(f"Orders data retrieved: {len(orders_data)} characters")

        # Combine all data for formatting
        raw_data = f"""
**VISITS DATA:**
{visits_data}

**CUSTOMER SEGMENTS DATA:**
{customers_data}

**ORDERS DATA:**
{orders_data}
"""
        logger.info(f"Combined data retrieved: {len(raw_data)} characters")

        # ⚠️ Check for "no data" scenarios - when queries return empty or zero results
        no_data_indicators = [
            "no data",
            "no records",
            "no results",
            "0 visits",
            "0 orders",
            "no visits",
            "no orders",
            "empty",
            "not found"
        ]

        # ⚠️ CRITICAL: Check if raw_data is an error message before formatting
        # Error messages often contain phrases like "issue", "error", "couldn't", "unable"
        error_indicators = [
            "encountered an issue",
            "couldn't generate",
            "couldn't determine",
            "unable to retrieve",
            "error",
            "failed"
        ]

        # Check each data source for emptiness
        def has_meaningful_data(data_str: str) -> bool:
            """Check if data string contains meaningful results (not just zeros or empty)"""
            import re
            lower_data = data_str.lower()
            logger.info(f"🔍 Checking data for meaningful content: {data_str[:300]}...")

            # Check for explicit "no data" indicators
            if any(ind in lower_data for ind in no_data_indicators):
                logger.info(f"❌ Found 'no data' indicator in: {data_str[:100]}")
                return False

            # Check for zero-only results in various formats:
            # - "Total: 0", "visits: 0", "total_visits: 0"
            # - "| 0 |" (markdown tables)
            # - "(0,)" (Python tuples)
            zero_patterns = [
                r"total[_\s]*\w*\s*[:=]\s*0\b",   # total: 0, total_visits: 0, etc.
                r"count\s*[:=]\s*0\b",            # count: 0
                r"visits\s*[:=]\s*0\b",           # visits: 0
                r"orders\s*[:=]\s*0\b",           # orders: 0
                r"\|\s*0\s*\|",                   # | 0 | in markdown tables
                r"\(0,?\)",                        # (0,) or (0) - Python tuples
            ]
            for pattern in zero_patterns:
                if re.search(pattern, lower_data):
                    logger.info(f"❌ Found zero pattern '{pattern}' in: {data_str[:100]}")
                    return False

            # Check for NULL results (database returned no value)
            # The query_db returns data like: {'total_visits': None}
            # When lowercased this becomes: {'total_visits': none}
            null_patterns = [
                r"'[^']*':\s*none",                # 'key': None (Python dict format) - MOST COMMON
                r'"[^"]*":\s*none',                # "key": None (JSON format)
                r"\(none,?\)",                     # (None,) or (none,)
                r":\s*none\s*[,})\]]",             # key: None, or key: None} or key: None) or key: None]
                r"=\s*none\b",                     # value = None
                r"\|\s*none\s*\|",                 # | None | in tables
                r"'[^']*':\s*null",                # 'key': null (dict format)
                r'"[^"]*":\s*null',                # "key": null (JSON format)
                r":\s*null\s*[,})\]]",             # key: null, or key: null}
                r"\|\s*null\s*\|",                 # | null | in tables
            ]
            for pattern in null_patterns:
                if re.search(pattern, lower_data):
                    logger.info(f"❌ Found NULL pattern '{pattern}' in: {data_str[:200]}")
                    return False

            # Also check for ALL values being None in a dict (e.g., "{'a': None, 'b': None}")
            # If the data section only contains None values, it's meaningless
            data_section_match = re.search(r"\*\*data:\*\*\s*(\{[^}]+\})", lower_data)
            if data_section_match:
                data_dict_str = data_section_match.group(1)
                # Check if all values in the dict are None
                values = re.findall(r":\s*([^,}]+)", data_dict_str)
                if values and all(v.strip() == "none" for v in values):
                    logger.info(f"❌ All values in data dict are None: {data_dict_str}")
                    return False

            # Check for "Result rows: 0" or "Rows returned: 0" indicating empty query results
            if "result rows: 0" in lower_data or "0 rows" in lower_data or "rows returned: 0" in lower_data:
                logger.info(f"❌ Found 0 rows in: {data_str[:100]}")
                return False
            # Check for "Not Available" which indicates the LLM couldn't find data
            if "not available" in lower_data:
                logger.info(f"❌ Found 'Not Available' in: {data_str[:100]}")
                return False
            # If it's very short, probably no real data
            if len(data_str.strip()) < 20:
                logger.info(f"❌ Data too short ({len(data_str.strip())} chars): {data_str}")
                return False

            logger.info(f"✅ Data appears meaningful: {data_str[:100]}...")
            return True

        has_visits = has_meaningful_data(visits_data)
        has_customers = has_meaningful_data(customers_data)
        has_orders = has_meaningful_data(orders_data)

        is_no_data = not has_visits and not has_customers and not has_orders
        is_error = any(indicator in raw_data.lower() for indicator in error_indicators)

        logger.info(f"Data check - visits: {has_visits}, customers: {has_customers}, orders: {has_orders}")

        # Handle "no new data" case - return a friendly greeting instead
        if is_no_data:
            logger.info("No new data found for the time period - returning friendly greeting")
            time_window_str = format_time_window(data_since)
            return f"""Hey, welcome back! 👋

Things have been pretty quiet since {time_window_str} - no new activity to report right now.

Feel free to ask me anything about your business data, or check back later for updates!"""

        if is_error:
            logger.warning(f"Raw data appears to be an error message, skipping LLM formatting to prevent hallucination")
            business_data = "I wasn't able to retrieve your business metrics right now. This might be due to a temporary issue. Feel free to ask me specific questions about your data!"
        else:
            # Format the raw data into a user-friendly response
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers.string import StrOutputParser
            from agent.config import get_llm

            format_prompt = ChatPromptTemplate.from_template("""Format this raw data into a friendly merchant update. Use ONLY exact numbers from the data — never invent. Skip sections with missing data. No emojis.

{raw_data}

**Output format (blank line before each header, bold key numbers):**

**This week's activity**
[1-2 sentences about visits. Bold numbers.]

**Sales**
[1 short sentence about orders.]

**Something to consider**
[1-2 sentences — actionable suggestion from the data.]
""")

            chain = format_prompt | get_llm() | StrOutputParser()
            formatted_output = chain.invoke({"raw_data": raw_data})

            # ⚠️ CRITICAL SAFETY CHECK: Use dedicated anti-hallucination module
            from agent.utils.anti_hallucination import sanitize_response, detect_hallucination

            is_hallucinated, reason = detect_hallucination(formatted_output, context="insights")

            if is_hallucinated:
                logger.error(f"⚠️ HALLUCINATION DETECTED AND BLOCKED: {reason}")
                logger.error(f"Blocked output (first 300 chars): {formatted_output[:300]}")
                business_data = "I wasn't able to retrieve valid business metrics. Please ask me specific questions about your data and I'll fetch the real numbers from your database."
            else:
                business_data = formatted_output
                logger.info(f"Formatted data passed hallucination check: {len(business_data)} characters")

    except Exception as e:
        logger.error(f"Failed to fetch business data: {e}", exc_info=True)
        business_data = "I wasn't able to retrieve your business metrics right now. This might be due to a temporary issue. Feel free to ask me specific questions about your data!"


    # ============================================
    # Human-like formatted message
    # ============================================

    # Calculate time window for personalized greeting
    time_window_str = format_time_window(data_since)

    proactive_message = f"""Hey! Here's what's been happening since {time_window_str}:

{business_data}
"""

    logger.info(f"Proactive insights generated: {len(proactive_message)} characters")
    return proactive_message


async def generate_monthly_report(
    merchant_id: str,
    user_email: str
) -> str:
    """
    Generates monthly business report for the last 30 days.

    Args:
        merchant_id: Merchant identifier for data isolation
        user_email: User email for logging

    Returns:
        Formatted markdown string ready to stream to user
    """
    from agent.tools import query_db

    logger.info(f"Generating monthly report for merchant {merchant_id} ({user_email})")

    # Query for last 30 days
    time_period = "in the last 30 days"

    business_data = ""
    try:
        logger.info("Fetching monthly metrics via parallel focused queries...")

        # Query 1: Total visits
        visits_data = query_db.invoke({
            "user_question": f"Total visits {time_period}",
            "merchant_id": merchant_id
        })

        # Query 2: Customer segments (LoyaltyProgramSummary - pre-aggregated, fast)
        customers_data = query_db.invoke({
            "user_question": "Customer segment distribution showing total members and active members per segment from LoyaltyProgramSummary (exclude the ALL row)",
            "merchant_id": merchant_id
        })

        # Query 3: Orders breakdown - use DailyPerformanceSummary which has performance_date column
        orders_data = query_db.invoke({
            "user_question": f"Total daily orders (daily_orders column) {time_period} from DailyPerformanceSummary table",
            "merchant_id": merchant_id
        })

        # Query 4: Revenue
        revenue_data = query_db.invoke({
            "user_question": f"Total revenue {time_period}",
            "merchant_id": merchant_id
        })

        # Query 5: Loyalty metrics (lifetime data, doesn't need date filter)
        loyalty_data = query_db.invoke({
            "user_question": "Loyalty score breakdown and points activity",
            "merchant_id": merchant_id
        })

        # Combine all data
        raw_data = f"""
**VISITS DATA:**
{visits_data}

**CUSTOMER SEGMENTS DATA:**
{customers_data}

**ORDERS DATA:**
{orders_data}

**REVENUE DATA:**
{revenue_data}

**LOYALTY DATA:**
{loyalty_data}
"""

        # Check for errors
        error_indicators = [
            "encountered an issue",
            "couldn't generate",
            "couldn't determine",
            "unable to retrieve",
            "error",
            "failed"
        ]

        is_error = any(indicator in raw_data.lower() for indicator in error_indicators)

        if is_error:
            logger.warning(f"Raw data appears to be an error message, skipping LLM formatting")
            business_data = "I wasn't able to retrieve your monthly business metrics right now. Feel free to ask me specific questions about your data!"
        else:
            # Format the data
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers.string import StrOutputParser
            from agent.config import get_llm

            format_prompt = ChatPromptTemplate.from_template("""Format this raw data into a concise monthly report. Use ONLY exact numbers — never invent. Each number appears ONCE. Skip missing sections. No emojis. Under 200 words.

{raw_data}

**Output format (blank line before each header, tables for segments/loyalty):**

**Monthly overview**
[2-3 sentences, general tone — save numbers for sections below.]

**Traffic**
Your store had **X visits** this month.

**Customer activity**
| Segment | Count |
|---------|-------|
| Regular | X |

**Sales**
You processed **X orders** generating **SAR X** in revenue.

**Loyalty**
[Table if data available]

**Want to explore more?**
Just ask me to dive deeper into any of these areas.
""")

            chain = format_prompt | get_llm() | StrOutputParser()
            formatted_output = chain.invoke({"raw_data": raw_data})

            # Anti-hallucination check
            from agent.utils.anti_hallucination import sanitize_response, detect_hallucination

            is_hallucinated, reason = detect_hallucination(formatted_output, context="insights")

            if is_hallucinated:
                logger.error(f"⚠️ HALLUCINATION DETECTED AND BLOCKED: {reason}")
                business_data = "I wasn't able to retrieve valid monthly business metrics. Please ask me specific questions about your data and I'll fetch the real numbers from your database."
            else:
                business_data = formatted_output
                logger.info(f"Monthly report formatted successfully: {len(business_data)} characters")

    except Exception as e:
        logger.error(f"Failed to fetch monthly report data: {e}", exc_info=True)
        business_data = "I wasn't able to retrieve your monthly business metrics right now. This might be due to a temporary issue. Feel free to ask me specific questions about your data!"

    monthly_message = f"""**Your Monthly Report**

{business_data}
"""

    logger.info(f"Monthly report generated: {len(monthly_message)} characters")
    return monthly_message


def format_time_window(since: datetime) -> str:
    """
    Formats datetime into human-readable time window.

    Examples:
    - "a few moments ago"
    - "3 hours ago"
    - "yesterday"
    - "3 days ago"
    - "last week"
    - "January 15"

    Args:
        since: Datetime to format

    Returns:
        Human-readable string
    """
    now = datetime.now(timezone.utc)
    delta = now - since

    if delta.days == 0:
        hours = delta.seconds // 3600
        if hours < 1:
            return "a few moments ago"
        elif hours == 1:
            return "1 hour ago"
        else:
            return f"{hours} hours ago"
    elif delta.days == 1:
        return "yesterday"
    elif delta.days < 7:
        return f"{delta.days} days ago"
    elif delta.days < 14:
        return "last week"
    else:
        return since.strftime("%B %d")
