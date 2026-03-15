"""
Deterministic SQL Compiler — Converts QueryIntent to valid MySQL.

This is the core of the Structured Output Decomposition approach.
It takes a structured query intent (from the LLM) and compiles it to
valid MySQL, guaranteeing:

- All column names are from the allowlist (no hallucination possible)
- Merchant isolation (WHERE idMerchant = X) is always applied
- Date functions are never used (literal dates only)
- SQL syntax is always valid

See ARCHITECTURE_RESEARCH.md §Pattern 2 and §Pattern 5.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from .query_schema import QueryIntent, TABLE_METADATA

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Main Compiler Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def compile_to_sql(
    intent: QueryIntent,
    table_name: str,
    merchant_id: str,
    current_date: str,
) -> dict:
    """
    Compile a QueryIntent to a MySQL query string.

    Args:
        intent: The structured query intent from the LLM
        table_name: The selected table name
        merchant_id: The merchant's ID for data isolation
        current_date: Today's date as YYYY-MM-DD string

    Returns:
        dict with:
            - 'query': The compiled SQL string (None on error)
            - 'error': Error message if compilation fails (None on success)
    """
    meta = TABLE_METADATA.get(table_name)
    if not meta:
        return {'query': None, 'error': f"Unknown table: {table_name}"}

    valid_columns = set(meta['columns'].keys())
    scope_warning = None  # Set if time range requested on lifetime table

    # ═══ Validate and build SELECT clause ═══
    select_parts = []
    has_aggregation = False

    for m in intent.metrics:
        # Validate column (allow "*" for COUNT(*))
        if m.column != "*":
            matched = _find_column(m.column, valid_columns)
            if not matched:
                return {
                    'query': None,
                    'error': (
                        f"Column `{m.column}` does not exist in `{table_name}`. "
                        f"Available: {', '.join(sorted(valid_columns))}"
                    )
                }
            col_name = matched
        else:
            col_name = "*"

        if m.aggregation and m.aggregation != "none":
            has_aggregation = True
            agg = m.aggregation.upper()
            col_ref = "*" if col_name == "*" else f"`{col_name}`"
            alias = f" AS `{m.alias}`" if m.alias else ""
            select_parts.append(f"{agg}({col_ref}){alias}")
        else:
            alias = f" AS `{m.alias}`" if m.alias else ""
            select_parts.append(f"`{col_name}`{alias}")

    if not select_parts:
        return {'query': None, 'error': "No columns specified in metrics"}

    # ═══ Add GROUP BY columns to SELECT (if aggregating) ═══
    validated_group_cols = []
    if intent.group_by:
        for gb_col in intent.group_by:
            matched = _find_column(gb_col, valid_columns)
            if not matched:
                return {
                    'query': None,
                    'error': f"GROUP BY column `{gb_col}` does not exist in `{table_name}`"
                }
            validated_group_cols.append(matched)
            # Prepend to SELECT if not already present
            col_backtick = f"`{matched}`"
            if col_backtick not in " ".join(select_parts):
                select_parts.insert(0, col_backtick)

    select_clause = ", ".join(select_parts)

    # ═══ Build WHERE clause ═══
    where_parts = [f"`idMerchant` = {merchant_id}"]

    # Default filters (e.g., isDeleted = 0)
    for df in meta.get('default_filters', []):
        where_parts.append(_build_condition(df['column'], df['operator'], df['value']))

    # Track default filter conditions to avoid duplicates
    default_conditions = set()
    for df in meta.get('default_filters', []):
        default_conditions.add((df['column'].lower(), df['operator'], df['value']))

    # User-specified filters
    for f in intent.filters:
        # Skip idMerchant if LLM included it (we already add it)
        if f.column.lower() == 'idmerchant':
            continue
        matched = _find_column(f.column, valid_columns)
        if not matched:
            logger.warning(
                f"Filter column `{f.column}` not in {table_name} — skipping"
            )
            continue
        # Skip if this duplicates a default filter
        if (matched.lower(), f.operator, f.value) in default_conditions:
            logger.info(f"Skipping duplicate default filter: {matched} {f.operator} {f.value}")
            continue
        where_parts.append(_build_condition(matched, f.operator, f.value))

    # ═══ Time range → WHERE conditions ═══
    time_col = meta.get('time_column')
    if intent.time_range and time_col:
        time_conditions = _resolve_time_range(
            intent.time_range, time_col, current_date
        )
        where_parts.extend(time_conditions)
    elif intent.time_range and not time_col:
        # Table has no time column — still compile query, but flag a scope warning
        logger.warning(
            f"Time range requested but {table_name} has no time column — adding scope warning"
        )
        scope_warning = (
            f"⚠️ DATA SCOPE: The {table_name} table contains LIFETIME totals only "
            f"and cannot be filtered to a specific time period. "
            f"The results below are ALL-TIME data, not limited to the requested dates."
        )

    where_clause = " AND ".join(where_parts)

    # ═══ GROUP BY clause ═══
    group_by_clause = ""
    if validated_group_cols and has_aggregation:
        group_by_clause = " GROUP BY " + ", ".join(
            f"`{c}`" for c in validated_group_cols
        )

    # ═══ ORDER BY clause ═══
    order_by_clause = ""
    if intent.order_by:
        ob_col = intent.order_by.column
        # Check if it's a valid column
        matched = _find_column(ob_col, valid_columns)
        if matched:
            direction = intent.order_by.direction.upper()
            order_by_clause = f" ORDER BY `{matched}` {direction}"
        else:
            # Check if it's an alias from a metric
            aliases = [m.alias for m in intent.metrics if m.alias]
            if ob_col in aliases:
                direction = intent.order_by.direction.upper()
                order_by_clause = f" ORDER BY `{ob_col}` {direction}"
            else:
                logger.warning(f"ORDER BY column `{ob_col}` not found — skipping")

    # ═══ LIMIT clause ═══
    limit_clause = ""
    if intent.limit:
        limit_clause = f" LIMIT {min(intent.limit, 100)}"
    else:
        limit_clause = " LIMIT 100"  # Safety default

    # ═══ Assemble ═══
    query = (
        f"SELECT {select_clause} "
        f"FROM `{table_name}` "
        f"WHERE {where_clause}"
        f"{group_by_clause}"
        f"{order_by_clause}"
        f"{limit_clause}"
    )

    logger.info(f"[compile_query] Compiled SQL: {query}")
    return {'query': query, 'error': None, 'scope_warning': scope_warning}


# ═══════════════════════════════════════════════════════════════════════════════
# Deterministic Time Resolution
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_time_range(
    time_range,
    time_column: str,
    current_date_str: str,
) -> list[str]:
    """
    Convert a TimeRange into WHERE conditions.

    For 'performance_date' → date comparison conditions.
    For 'year_month' (MonthlyPerformanceSummary) → year/month integer conditions.
    For 'registration_date' / 'last_visit_date' → datetime comparison.
    """
    conditions = []
    start_str = None
    end_str = None

    # Resolve preset to start/end dates
    if time_range.preset:
        start_str, end_str = resolve_time_preset(
            time_range.preset, current_date_str
        )
    elif time_range.custom_start:
        start_str = time_range.custom_start
        end_str = time_range.custom_end or current_date_str

    if not start_str:
        return conditions

    # Special case: MonthlyPerformanceSummary uses year/month integers
    if time_column == 'year_month':
        start_d = date.fromisoformat(start_str)
        end_d = date.fromisoformat(end_str)

        if start_d.year == end_d.year and start_d.month == end_d.month:
            # Single month
            conditions.append(f"`year` = {start_d.year}")
            conditions.append(f"`month` = {start_d.month}")
        elif start_d.year == end_d.year:
            # Same year, range of months
            conditions.append(f"`year` = {start_d.year}")
            conditions.append(f"`month` >= {start_d.month}")
            conditions.append(f"`month` <= {end_d.month}")
        else:
            # Cross-year range — use (year, month) comparison
            conditions.append(
                f"(`year` > {start_d.year} OR "
                f"(`year` = {start_d.year} AND `month` >= {start_d.month}))"
            )
            conditions.append(
                f"(`year` < {end_d.year} OR "
                f"(`year` = {end_d.year} AND `month` <= {end_d.month}))"
            )
    else:
        # Standard date column comparison
        col = f"`{time_column}`"
        if start_str == end_str:
            # Single day
            conditions.append(f"{col} >= '{start_str}'")
            conditions.append(f"{col} < '{start_str}' + INTERVAL 1 DAY")
        else:
            # Use < next_day instead of <= end_date for DATETIME safety.
            # DATETIME <= '2026-02-08' only matches midnight, missing the rest
            # of the day. < '2026-02-09' captures the full day correctly.
            # For DATE columns, < next_day is equivalent to <= end_date.
            end_d = date.fromisoformat(end_str) + timedelta(days=1)
            conditions.append(f"{col} >= '{start_str}'")
            conditions.append(f"{col} < '{end_d.isoformat()}'")

    return conditions


def resolve_time_preset(preset: str, current_date_str: str) -> tuple[str, str]:
    """
    Resolve a time preset to (start_date, end_date) as YYYY-MM-DD strings.

    This is the ONLY place date math happens — deterministic, never the LLM.
    """
    d = date.fromisoformat(current_date_str)

    if preset == 'today':
        return current_date_str, current_date_str

    elif preset == 'yesterday':
        y = (d - timedelta(days=1)).isoformat()
        return y, y

    elif preset == 'last_7_days':
        start = (d - timedelta(days=7)).isoformat()
        return start, current_date_str

    elif preset == 'this_week':
        monday = (d - timedelta(days=d.weekday())).isoformat()
        return monday, current_date_str

    elif preset == 'last_week':
        this_monday = d - timedelta(days=d.weekday())
        last_monday = (this_monday - timedelta(days=7)).isoformat()
        last_sunday = (this_monday - timedelta(days=1)).isoformat()
        return last_monday, last_sunday

    elif preset == 'last_30_days':
        # "last 30 days" = today + 29 previous days = 30 days total
        start = (d - timedelta(days=29)).isoformat()
        return start, current_date_str

    elif preset == 'this_month':
        first = d.replace(day=1).isoformat()
        return first, current_date_str

    elif preset == 'last_month':
        first_of_this = d.replace(day=1)
        last_of_prev = first_of_this - timedelta(days=1)
        first_of_prev = last_of_prev.replace(day=1).isoformat()
        return first_of_prev, last_of_prev.isoformat()

    elif preset == 'last_3_months':
        month = d.month - 3
        year = d.year
        while month <= 0:
            month += 12
            year -= 1
        start = date(year, month, 1).isoformat()
        return start, current_date_str

    elif preset == 'last_90_days':
        start = (d - timedelta(days=89)).isoformat()
        return start, current_date_str

    elif preset == 'this_year':
        first = date(d.year, 1, 1).isoformat()
        return first, current_date_str

    elif preset == 'last_year':
        first = date(d.year - 1, 1, 1).isoformat()
        last = date(d.year - 1, 12, 31).isoformat()
        return first, last

    elif preset == 'last_6_months':
        month = d.month - 6
        year = d.year
        while month <= 0:
            month += 12
            year -= 1
        start = date(year, month, 1).isoformat()
        return start, current_date_str

    elif preset == 'last_14_days':
        start = (d - timedelta(days=14)).isoformat()
        return start, current_date_str

    elif preset == 'last_12_months':
        start = date(d.year - 1, d.month, 1).isoformat()
        return start, current_date_str

    else:
        logger.warning(f"Unknown time preset: {preset} — defaulting to today")
        return current_date_str, current_date_str


# ═══════════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _find_column(name: str, valid_columns: set) -> Optional[str]:
    """Case-insensitive column lookup. Returns correctly-cased name or None."""
    name_lower = name.lower()
    for col in valid_columns:
        if col.lower() == name_lower:
            return col
    return None


def _build_condition(column: str, operator: str, value: str) -> str:
    """Build a single WHERE condition string."""
    col_ref = f"`{column}`"

    if operator in ("in", "not_in"):
        values = [v.strip() for v in value.split(",")]
        if all(_is_numeric(v) for v in values):
            value_list = ", ".join(values)
        else:
            value_list = ", ".join(f"'{v}'" for v in values)
        op = "IN" if operator == "in" else "NOT IN"
        return f"{col_ref} {op} ({value_list})"

    if _is_numeric(value):
        return f"{col_ref} {operator} {value}"
    else:
        return f"{col_ref} {operator} '{value}'"


def _is_numeric(value: str) -> bool:
    """Check if a string value is numeric."""
    try:
        float(value)
        return True
    except ValueError:
        return False
