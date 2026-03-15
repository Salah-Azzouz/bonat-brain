"""
Entity Tracker Module for Session Context Awareness

Provides heuristic-based entity extraction and reference resolution
to enable natural follow-up questions across conversation turns.

Example:
    Turn 1: "Show me revenue for Riyadh branch last week"
    Turn 2: "What about that branch's visits?"  -> Resolves "that branch" to "Riyadh"
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from calendar import monthrange


# =============================================================================
# ENTITY EXTRACTION PATTERNS
# =============================================================================

# Branch patterns - Saudi cities and common branch references
BRANCH_PATTERNS = [
    r'\b(riyadh|الرياض)\b',
    r'\b(jeddah|جدة)\b',
    r'\b(dammam|الدمام)\b',
    r'\b(mecca|makkah|مكة)\b',
    r'\b(medina|madinah|المدينة)\b',
    r'\b(khobar|الخبر)\b',
    r'\b(tabuk|تبوك)\b',
    r'\b(abha|أبها)\b',
    r'\b(online|أونلاين|اونلاين)\b',
    r'\b(all\s+branches|كل\s+الفروع)\b',
]

# Dynamic branch pattern - catches "X branch" or "branch X"
BRANCH_DYNAMIC_PATTERNS = [
    r'(?:branch|فرع)\s+(?:in\s+)?([A-Za-zء-ي\s]+?)(?:\s|$|,|\.|\')',
    r'([A-Za-zء-ي]+)\s+(?:branch|فرع)',
]

# Metric keywords mapped to canonical names
METRIC_KEYWORDS = {
    "revenue": ["revenue", "sales", "income", "earnings", "إيرادات", "مبيعات", "دخل"],
    "visits": ["visits", "visit", "traffic", "footfall", "زيارات", "زيارة"],
    "orders": ["orders", "order", "transactions", "purchases", "طلبات", "طلب", "معاملات"],
    "customers": ["customers", "customer", "clients", "users", "عملاء", "عميل", "مستخدمين"],
    "aov": ["average order", "aov", "avg order", "order value", "متوسط الطلب", "قيمة الطلب"],
    "loyalty_points": ["loyalty points", "points", "نقاط الولاء", "نقاط"],
    "redemptions": ["redemptions", "redeemed", "redeem", "استبدال", "استردات"],
    "new_customers": ["new customers", "new customer", "عملاء جدد"],
    "returning_customers": ["returning customers", "repeat customers", "عملاء عائدين"],
}

# Segment patterns
SEGMENT_PATTERNS = {
    "superfan": [r"super\s*fan", r"سوبر\s*فان", r"المميزين"],
    "loyal": [r"\bloyal\b", r"الأوفياء", r"وفي"],
    "regular": [r"\bregular\b", r"الدائمين", r"منتظم"],
    "new": [r"\bnew\s+customer", r"\bnew\s+segment", r"الجدد", r"جديد"],
    "lost": [r"\blost\b", r"المفقودين", r"مفقود", r"churned", r"inactive"],
    "potential": [r"\bpotential\b", r"محتمل"],
    "birthday": [r"\bbirthday\b", r"عيد\s*ميلاد", r"ميلاد"],
}

# Time range patterns
TIME_PATTERNS = [
    # Relative periods
    (r"last\s+(\d+)\s+days?", "relative_days"),
    (r"last\s+(\d+)\s+weeks?", "relative_weeks"),
    (r"last\s+(\d+)\s+months?", "relative_months"),
    (r"past\s+(\d+)\s+days?", "relative_days"),
    (r"past\s+(\d+)\s+weeks?", "relative_weeks"),
    (r"this\s+week", "this_week"),
    (r"this\s+month", "this_month"),
    (r"this\s+year", "this_year"),
    (r"last\s+week", "last_week"),
    (r"last\s+month", "last_month"),
    (r"last\s+year", "last_year"),
    (r"\btoday\b", "today"),
    (r"\byesterday\b", "yesterday"),
    # Month names
    (r"\b(january|jan)\b", "month_january"),
    (r"\b(february|feb)\b", "month_february"),
    (r"\b(march|mar)\b", "month_march"),
    (r"\b(april|apr)\b", "month_april"),
    (r"\b(may)\b", "month_may"),
    (r"\b(june|jun)\b", "month_june"),
    (r"\b(july|jul)\b", "month_july"),
    (r"\b(august|aug)\b", "month_august"),
    (r"\b(september|sep|sept)\b", "month_september"),
    (r"\b(october|oct)\b", "month_october"),
    (r"\b(november|nov)\b", "month_november"),
    (r"\b(december|dec)\b", "month_december"),
    # Arabic time expressions
    (r"الأسبوع\s+الماضي", "last_week"),
    (r"الشهر\s+الماضي", "last_month"),
    (r"السنة\s+الماضية", "last_year"),
    (r"اليوم", "today"),
    (r"أمس", "yesterday"),
]

# Reference patterns for pronoun resolution
REFERENCE_PATTERNS = {
    "branch": [
        r"\b(that|the|same|this)\s+branch\b",
        r"\bthere\b(?!\s+are|\s+is)",  # "How about there?" but not "there are"
        r"نفس\s+الفرع",
        r"ذلك\s+الفرع",
    ],
    "metric": [
        r"\b(same|that|the)\s+(metric|number|stat|figure|kpi)\b",
        r"نفس\s+(المقياس|الرقم)",
    ],
    "segment": [
        r"\b(those|these|the|that)\s+(customer|segment|group)s?\b",
        r"\bthem\b",
        r"هؤلاء\s+العملاء",
    ],
    "time_range": [
        r"\b(same|that|the)\s+(period|time|timeframe|range|duration)\b",
        r"نفس\s+الفترة",
    ],
}


# =============================================================================
# ENTITY EXTRACTION FUNCTIONS
# =============================================================================

def extract_entities(text: str) -> Dict:
    """
    Extract entities from text using heuristic patterns.

    Args:
        text: User query or response text

    Returns:
        Dictionary with extracted entities:
        {
            "branches": ["Riyadh"],
            "metrics": ["revenue", "visits"],
            "segments": ["lost"],
            "campaigns": [],
            "time_range": {"type": "relative", "value": "7 days", "raw": "last week"}
        }
    """
    text_lower = text.lower()

    entities = {
        "branches": [],
        "metrics": [],
        "segments": [],
        "campaigns": [],
        "time_range": None,
    }

    # Extract branches
    entities["branches"] = _extract_branches(text_lower)

    # Extract metrics
    entities["metrics"] = _extract_metrics(text_lower)

    # Extract segments
    entities["segments"] = _extract_segments(text_lower)

    # Extract time range and resolve to actual dates
    time_range = _extract_time_range(text_lower)
    if time_range:
        entities["time_range"] = resolve_time_range(time_range)
    else:
        entities["time_range"] = None

    # Log extraction results
    if any([entities["branches"], entities["metrics"], entities["segments"], entities["time_range"]]):
        logging.debug(f"[Entity Tracker] Extracted entities: {entities}")

    return entities


def _extract_branches(text: str) -> List[str]:
    """Extract branch names from text."""
    branches = []

    # Common false positives to filter out
    FALSE_POSITIVES = {
        "the", "a", "an", "my", "our", "your", "that", "this", "last", "next",
        "all", "every", "each", "some", "any", "first", "second", "third",
        # Arabic false positives (common words that might match patterns)
        "إيرادات", "مبيعات", "زيارات", "طلبات", "عملاء", "نقاط",
    }

    # Check static patterns
    for pattern in BRANCH_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # Skip if it's a false positive
            if match.lower() in FALSE_POSITIVES:
                continue
            # Normalize branch name
            branch = _normalize_branch(match)
            if branch and branch not in branches:
                branches.append(branch)

    # Check dynamic patterns (only if no static matches found)
    if not branches:
        for pattern in BRANCH_DYNAMIC_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                branch = match.strip()
                # Filter out common false positives
                if branch.lower() not in FALSE_POSITIVES:
                    normalized = _normalize_branch(branch)
                    if normalized and normalized not in branches:
                        branches.append(normalized)

    return branches[:3]  # Limit to 3 most recent


def _normalize_branch(branch: str) -> Optional[str]:
    """Normalize branch name to canonical form."""
    branch = branch.strip().lower()

    # Mapping of variations to canonical names
    mappings = {
        "riyadh": "Riyadh", "الرياض": "Riyadh",
        "jeddah": "Jeddah", "جدة": "Jeddah",
        "dammam": "Dammam", "الدمام": "Dammam",
        "mecca": "Mecca", "makkah": "Mecca", "مكة": "Mecca",
        "medina": "Medina", "madinah": "Medina", "المدينة": "Medina",
        "khobar": "Khobar", "الخبر": "Khobar",
        "tabuk": "Tabuk", "تبوك": "Tabuk",
        "abha": "Abha", "أبها": "Abha",
        "online": "Online", "أونلاين": "Online", "اونلاين": "Online",
        "all branches": "All Branches", "كل الفروع": "All Branches",
    }

    return mappings.get(branch, branch.title() if len(branch) > 2 else None)


def _extract_metrics(text: str) -> List[str]:
    """Extract metric names from text."""
    metrics = []

    for canonical, keywords in METRIC_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in text:
                if canonical not in metrics:
                    metrics.append(canonical)
                break

    return metrics[:3]  # Limit to 3


def _extract_segments(text: str) -> List[str]:
    """Extract customer segment names from text."""
    segments = []

    for segment_name, patterns in SEGMENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                if segment_name not in segments:
                    segments.append(segment_name)
                break

    return segments[:2]  # Limit to 2


def _extract_time_range(text: str) -> Optional[Dict]:
    """Extract time range from text."""
    for pattern, time_type in TIME_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw_match = match.group(0)

            # Handle numeric extractions (e.g., "last 7 days")
            if time_type.startswith("relative_"):
                num = int(match.group(1))
                unit = time_type.replace("relative_", "")
                return {
                    "type": "relative",
                    "value": f"{num} {unit}",
                    "raw": raw_match
                }

            # Handle month names
            if time_type.startswith("month_"):
                month = time_type.replace("month_", "").title()
                return {
                    "type": "month",
                    "value": month,
                    "raw": raw_match
                }

            # Handle other types
            return {
                "type": time_type,
                "value": time_type.replace("_", " "),
                "raw": raw_match
            }

    return None


def resolve_time_range(time_range: Dict, reference_date: datetime = None) -> Dict:
    """
    Resolve a relative time range to actual dates.

    This ensures that "last week" mentioned on Monday stays consistent
    even if the conversation continues on Tuesday.

    Args:
        time_range: Dict with type, value, raw from _extract_time_range
        reference_date: The date to resolve relative to (defaults to now)

    Returns:
        Updated time_range dict with start_date and end_date added
    """
    if not time_range:
        return time_range

    if reference_date is None:
        from agent.config import get_merchant_now
        ref = get_merchant_now()
    else:
        ref = reference_date
    today = ref.replace(hour=0, minute=0, second=0, microsecond=0)

    time_type = time_range.get("type", "")
    value = time_range.get("value", "")

    start_date = None
    end_date = today

    # Handle relative periods (e.g., "7 days", "2 weeks")
    if time_type == "relative":
        parts = value.split()
        if len(parts) >= 2:
            num = int(parts[0])
            unit = parts[1].rstrip('s')  # Remove plural

            if unit == "day":
                start_date = today - timedelta(days=num)
            elif unit == "week":
                start_date = today - timedelta(weeks=num)
            elif unit == "month":
                start_date = today - timedelta(days=num * 30)  # Approximate

    # Handle named periods
    elif time_type == "today":
        start_date = today
        end_date = today

    elif time_type == "yesterday":
        start_date = today - timedelta(days=1)
        end_date = today - timedelta(days=1)

    elif time_type == "this_week":
        # Start of current week (Monday)
        start_date = today - timedelta(days=today.weekday())
        end_date = today

    elif time_type == "last_week":
        # Previous week Monday to Sunday
        start_date = today - timedelta(days=today.weekday() + 7)
        end_date = start_date + timedelta(days=6)

    elif time_type == "this_month":
        start_date = today.replace(day=1)
        end_date = today

    elif time_type == "last_month":
        # First day of previous month
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        start_date = last_of_prev_month.replace(day=1)
        end_date = last_of_prev_month

    elif time_type == "this_year":
        start_date = today.replace(month=1, day=1)
        end_date = today

    elif time_type == "last_year":
        start_date = today.replace(year=today.year - 1, month=1, day=1)
        end_date = today.replace(year=today.year - 1, month=12, day=31)

    elif time_type == "month":
        # Specific month name (e.g., "January")
        month_name = value.lower()
        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12
        }
        month_num = month_map.get(month_name)
        if month_num:
            # Assume current year, or previous year if month is in the future
            year = today.year
            if month_num > today.month:
                year -= 1
            start_date = datetime(year, month_num, 1)
            _, last_day = monthrange(year, month_num)
            end_date = datetime(year, month_num, last_day)

    # Add resolved dates to the time_range dict
    if start_date:
        time_range["start_date"] = start_date.strftime("%Y-%m-%d")
        time_range["end_date"] = end_date.strftime("%Y-%m-%d")
        time_range["resolved_at"] = ref.strftime("%Y-%m-%d %H:%M:%S")

    return time_range


# =============================================================================
# CONTEXT AGGREGATION
# =============================================================================

def aggregate_entity_context(messages: List[Dict]) -> Dict:
    """
    Aggregate entity context from conversation history.

    Args:
        messages: List of message documents from MongoDB (most recent first)

    Returns:
        Aggregated context:
        {
            "last_branches": ["Riyadh", "Online"],
            "last_metrics": ["revenue", "visits"],
            "last_segments": ["lost"],
            "last_time_range": {"type": "relative", "value": "7 days"}
        }
    """
    context = {
        "last_branches": [],
        "last_metrics": [],
        "last_segments": [],
        "last_time_range": None,
    }

    # Process messages (already sorted most recent first)
    for message in messages:
        # Try to get pre-extracted entities
        entities = message.get("entities", {})

        # If no pre-extracted entities, extract from query text
        if not entities:
            user_query = message.get("user_query", "")
            if user_query:
                entities = extract_entities(user_query)

        # Aggregate branches (keep unique, most recent first)
        for branch in entities.get("branches", []):
            if branch not in context["last_branches"]:
                context["last_branches"].append(branch)

        # Aggregate metrics
        for metric in entities.get("metrics", []):
            if metric not in context["last_metrics"]:
                context["last_metrics"].append(metric)

        # Aggregate segments
        for segment in entities.get("segments", []):
            if segment not in context["last_segments"]:
                context["last_segments"].append(segment)

        # Get most recent time range
        if not context["last_time_range"] and entities.get("time_range"):
            context["last_time_range"] = entities["time_range"]

    # Limit lists
    context["last_branches"] = context["last_branches"][:3]
    context["last_metrics"] = context["last_metrics"][:3]
    context["last_segments"] = context["last_segments"][:2]

    return context


# =============================================================================
# REFERENCE RESOLUTION
# =============================================================================

def detect_references(query: str) -> Dict[str, bool]:
    """
    Detect which entity types are referenced by pronouns in the query.

    Args:
        query: User's query text

    Returns:
        Dictionary indicating which references were detected:
        {"branch": True, "metric": False, "segment": False, "time_range": False}
    """
    query_lower = query.lower()
    detected = {}

    for ref_type, patterns in REFERENCE_PATTERNS.items():
        detected[ref_type] = any(
            re.search(pattern, query_lower, re.IGNORECASE)
            for pattern in patterns
        )

    return detected


def has_explicit_time_range(query: str) -> bool:
    """
    Check if a query contains an explicit time specification.

    This helps determine if the user is specifying a NEW time range
    or implicitly continuing with the previous one.

    Args:
        query: User's query text

    Returns:
        True if query contains explicit time specification
    """
    query_lower = query.lower()

    for pattern, _ in TIME_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return True

    return False


def resolve_references(query: str, context: Dict) -> Tuple[str, Dict]:
    """
    Resolve pronoun references in query using entity context.

    Note: This function detects references but relies on the LLM to do
    the actual resolution using the injected context. It returns metadata
    about what was detected for logging purposes.

    Args:
        query: User's raw query
        context: Entity context from conversation

    Returns:
        Tuple of (original_query, detected_references_metadata)
    """
    detected = detect_references(query)
    resolutions = {}

    if detected.get("branch") and context.get("last_branches"):
        resolutions["branch_reference"] = context["last_branches"][0]

    if detected.get("metric") and context.get("last_metrics"):
        resolutions["metric_reference"] = context["last_metrics"][0]

    if detected.get("segment") and context.get("last_segments"):
        resolutions["segment_reference"] = context["last_segments"][0]

    if detected.get("time_range") and context.get("last_time_range"):
        resolutions["time_range_reference"] = context["last_time_range"].get("raw", "")

    if resolutions:
        logging.info(f"[Entity Tracker] Detected references: {resolutions}")

    return query, resolutions


# =============================================================================
# CONTEXT FORMATTING FOR PROMPT INJECTION
# =============================================================================

def format_entity_context(context: Dict) -> str:
    """
    Format entity context for injection into the system prompt.

    Args:
        context: Aggregated entity context

    Returns:
        Formatted string for prompt injection
    """
    if not context:
        return "No previous entity context available."

    # Check if any context exists
    has_context = (
        context.get("last_branches") or
        context.get("last_metrics") or
        context.get("last_segments") or
        context.get("last_time_range")
    )

    if not has_context:
        return "No previous entity context available."

    lines = []

    if context.get("last_branches"):
        branches = ", ".join(context["last_branches"])
        lines.append(f"- Last branches mentioned: {branches}")

    if context.get("last_metrics"):
        metrics = ", ".join(context["last_metrics"])
        lines.append(f"- Last metrics discussed: {metrics}")

    if context.get("last_segments"):
        segments = ", ".join(context["last_segments"])
        lines.append(f"- Last customer segments: {segments}")

    if context.get("last_time_range"):
        tr = context["last_time_range"]
        time_str = tr.get("raw", tr.get("value", "unknown"))
        # Include resolved dates if available
        if tr.get("start_date") and tr.get("end_date"):
            lines.append(f"- Last time range: {time_str} (resolved: {tr['start_date']} to {tr['end_date']})")
        else:
            lines.append(f"- Last time range: {time_str}")

    return "\n".join(lines)
