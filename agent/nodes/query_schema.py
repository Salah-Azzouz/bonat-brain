"""
Structured Query Schema — Column allowlists and Pydantic models.

Instead of generating raw SQL, the LLM outputs a QueryIntent (structured JSON)
that specifies WHAT data to retrieve. Deterministic code (compile_query.py)
then compiles it to valid MySQL.

This eliminates column hallucination by constraining the LLM to known column names.

See ARCHITECTURE_RESEARCH.md §Pattern 5 and §Option B for the industry research.
"""

from __future__ import annotations

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, create_model


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models — What the LLM outputs
# ═══════════════════════════════════════════════════════════════════════════════

class MetricSelection(BaseModel):
    """A column to SELECT, optionally with an aggregation function."""
    column: str = Field(
        description="Column name from the table's available columns, or '*' for COUNT(*)"
    )
    aggregation: Literal["sum", "count", "avg", "max", "min", "none"] = Field(
        default="none",
        description="Aggregation function. 'none' = raw value. 'count' with column='*' = COUNT(*)."
    )
    alias: Optional[str] = Field(
        default=None,
        description="Optional alias for the result column"
    )


class FilterCondition(BaseModel):
    """A WHERE condition to filter results."""
    column: str = Field(description="Column name to filter on")
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "in", "not_in"] = Field(
        description="Comparison operator"
    )
    value: str = Field(
        description=(
            "Filter value. For 'in'/'not_in', comma-separated: 'superFan,loyal'. "
            "For dates, use YYYY-MM-DD."
        )
    )


class OrderByClause(BaseModel):
    """Sorting specification."""
    column: str = Field(description="Column to sort by")
    direction: Literal["asc", "desc"] = Field(default="desc")


class TimeRange(BaseModel):
    """
    Time range specification.

    Use a preset for common ranges (compiler resolves deterministically).
    Use custom_start/custom_end for specific date ranges.
    """
    preset: Optional[str] = Field(
        default=None,
        description=(
            "Time preset: 'today', 'yesterday', 'last_7_days', 'this_week', "
            "'last_week', 'this_month', 'last_month', 'last_30_days', "
            "'last_3_months', 'last_90_days', 'this_year', 'last_year'"
        )
    )
    custom_start: Optional[str] = Field(
        default=None,
        description="Custom start date YYYY-MM-DD (when preset is not sufficient)"
    )
    custom_end: Optional[str] = Field(
        default=None,
        description="Custom end date YYYY-MM-DD (when preset is not sufficient)"
    )


class QueryIntent(BaseModel):
    """
    Structured query intent — the LLM's output.

    Replaces raw SQL generation. The LLM fills in this structure,
    and deterministic code compiles it to valid MySQL.
    """
    metrics: List[MetricSelection] = Field(
        description="Columns to select, with optional aggregation"
    )
    filters: List[FilterCondition] = Field(
        default_factory=list,
        description="WHERE conditions (idMerchant is auto-added — do NOT include it)"
    )
    group_by: List[str] = Field(
        default_factory=list,
        description="Columns to GROUP BY when using aggregations across groups"
    )
    order_by: Optional[OrderByClause] = Field(
        default=None,
        description="Sort order for results"
    )
    limit: Optional[int] = Field(
        default=None,
        description="Max rows to return (e.g., 5 for 'top 5')"
    )
    time_range: Optional[TimeRange] = Field(
        default=None,
        description="Time range filter. Only for tables with a time column."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Table Column Metadata — The Allowlist
# ═══════════════════════════════════════════════════════════════════════════════
#
# For each table:
#   columns     — dict of column_name → description (what the LLM sees)
#   time_column — date column for time filtering (None = lifetime table)
#   default_filters — always-applied filters (e.g., isDeleted = 0)
#   notes       — special instructions injected into the LLM prompt

# ── Load TABLE_METADATA from YAML semantic model ──
# The YAML file (semantic_models/bonat.yaml) is the single source of truth.
# get_table_metadata() returns the exact same dict shape as the old hardcoded version.
from agent.semantic_model import get_semantic_model as _get_semantic_model
TABLE_METADATA = _get_semantic_model().get_table_metadata()


# ═══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

def get_column_list_for_prompt(table_name: str) -> str:
    """Format available columns as a readable list for the LLM prompt."""
    meta = TABLE_METADATA.get(table_name)
    if not meta:
        return ""
    lines = []
    for col, desc in meta['columns'].items():
        lines.append(f"  - `{col}`: {desc}")
    return "\n".join(lines)


def get_valid_columns(table_name: str) -> set:
    """Get the set of valid column names for a table (case-sensitive)."""
    meta = TABLE_METADATA.get(table_name)
    if not meta:
        return set()
    return set(meta['columns'].keys())


def get_table_notes(table_name: str) -> str:
    """Get the special notes for a table."""
    meta = TABLE_METADATA.get(table_name)
    if not meta:
        return ""
    return meta.get('notes', '')


def get_time_column(table_name: str) -> str | None:
    """Get the time column for a table (None if lifetime table)."""
    meta = TABLE_METADATA.get(table_name)
    if not meta:
        return None
    return meta.get('time_column')


def get_time_presets_for_prompt() -> str:
    """Format time presets as a readable list for the LLM prompt."""
    return """Available time presets (compiler resolves dates automatically):
  - "today": Today only
  - "yesterday": Yesterday only
  - "last_7_days": 7 days counting back from today (includes today). Example: if today is Wednesday Feb 11, range = Feb 5 → Feb 11
  - "this_week": Current week from Monday to today. Example: if today is Wednesday Feb 11, range = Monday Feb 9 → Feb 11
  - "last_week": The PREVIOUS full Monday-to-Sunday week. Example: if today is Wednesday Feb 11, range = Monday Feb 3 → Sunday Feb 9
  - "this_month": First of this month to today. Example: if today is Feb 11, range = Feb 1 → Feb 11
  - "last_month": Full previous calendar month. Example: if today is Feb 11, range = Jan 1 → Jan 31
  - "last_14_days": 14 days counting back from today (for "past 2 weeks")
  - "last_30_days": 30 days counting back from today (includes today)
  - "last_3_months": From 3 months ago (1st of that month) to today
  - "last_90_days": 90 days counting back from today
  - "this_year": January 1 to today
  - "last_year": Full previous calendar year (Jan 1 → Dec 31)
Or use custom_start / custom_end for specific date ranges (YYYY-MM-DD).

⚠️ IMPORTANT — "last 7 days" ≠ "last week":
  - "last 7 days" / "past week" / "this past week" / "آخر ٧ أيام" → use preset "last_7_days" (7 days back from today)
  - "last week" / "previous week" / "آخر أسبوع" / "الأسبوع الماضي" → use preset "last_week" (previous Monday to Sunday)
  - "last month" / "آخر شهر" / "الشهر الماضي" → use preset "last_month" (full previous calendar month)
  - When in doubt, prefer "last_7_days" unless the user explicitly says "last week", "previous week", "آخر أسبوع", or "الأسبوع الماضي"."""


# ═══════════════════════════════════════════════════════════════════════════════
# Enum-Constrained Dynamic Models (Constrained Decoding)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Instead of the generic QueryIntent (where `column` is a free `str`),
# these table-specific models constrain `column` to an enum of valid names
# via JSON Schema {"enum": [...]}.
#
# When OpenAI processes this schema, its token decoder physically cannot
# generate a column name outside the enum — eliminating hallucination.
# (Based on the PICARD paper's constrained-decoding approach to text-to-SQL.)

_table_model_cache: dict[str, type] = {}


def build_table_query_intent(table_name: str) -> type:
    """
    Build a table-specific QueryIntent model with enum-constrained columns.

    The returned model is identical in structure to QueryIntent, but:
    - MetricSelection.column is constrained to the table's column names (+ '*')
    - FilterCondition.column is constrained to the table's column names

    This means OpenAI's structured output will reject any token sequence
    that doesn't match a valid column name — zero hallucination possible.

    Results are cached per table name for performance.
    """
    if table_name in _table_model_cache:
        return _table_model_cache[table_name]

    meta = TABLE_METADATA.get(table_name)
    if not meta:
        return QueryIntent

    columns = sorted(meta['columns'].keys())
    columns_with_star = ['*'] + columns

    # ═══ Build sub-models with enum-constrained columns ═══

    TableMetric = create_model(
        f'{table_name}_Metric',
        column=(str, Field(
            description="Column name from the table's available columns, or '*' for COUNT(*)",
            json_schema_extra={"enum": columns_with_star},
        )),
        aggregation=(
            Literal["sum", "count", "avg", "max", "min", "none"],
            Field(default="none", description="Aggregation function. Use 'count' with column='*' for COUNT(*).")
        ),
        alias=(Optional[str], Field(default=None, description="Optional alias for the result column")),
    )

    TableFilter = create_model(
        f'{table_name}_Filter',
        column=(str, Field(
            description="Column name to filter on",
            json_schema_extra={"enum": columns},
        )),
        operator=(
            Literal["=", "!=", ">", ">=", "<", "<=", "in", "not_in"],
            Field(description="Comparison operator")
        ),
        value=(str, Field(
            description="Filter value. For 'in'/'not_in', comma-separated: 'superFan,loyal'. For dates, use YYYY-MM-DD."
        )),
    )

    TableOrderBy = create_model(
        f'{table_name}_OrderBy',
        column=(str, Field(description="Column or metric alias to sort by")),
        direction=(Literal["asc", "desc"], Field(default="desc")),
    )

    TableQueryIntent = create_model(
        f'{table_name}_QueryIntent',
        metrics=(List[TableMetric], Field(description="Columns to select, with optional aggregation")),
        filters=(List[TableFilter], Field(
            default_factory=list,
            description="WHERE conditions (idMerchant is auto-added — do NOT include it)"
        )),
        group_by=(List[str], Field(
            default_factory=list,
            description="Columns to GROUP BY when using aggregations across groups"
        )),
        order_by=(Optional[TableOrderBy], Field(default=None, description="Sort order for results")),
        limit=(Optional[int], Field(default=None, description="Max rows to return (e.g., 5 for 'top 5')")),
        time_range=(Optional[TimeRange], Field(
            default=None,
            description="Time range filter. Only for tables with a time column."
        )),
    )

    _table_model_cache[table_name] = TableQueryIntent
    return TableQueryIntent
