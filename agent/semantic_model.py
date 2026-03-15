"""
Semantic Model Loader — Generic YAML-to-Python bridge.

Loads a YAML semantic model and provides the same data structures
that the pipeline code expects (TABLE_METADATA dicts, intent maps,
column corrections, routing examples, etc.).

This is the single integration point between the YAML "source of truth"
and all Python modules that consume table metadata.

Usage:
    from agent.semantic_model import get_semantic_model
    model = get_semantic_model()
    table_meta = model.get_table_metadata()        # Same shape as old TABLE_METADATA
    intent_map = model.get_intent_category_map()    # Same as old INTENT_CATEGORY_TABLE_MAP
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml


class SemanticModel:
    """Generic loader for YAML semantic models."""

    def __init__(self, yaml_path: str) -> None:
        self._path = yaml_path
        self._raw: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Parse the YAML file into memory."""
        path = Path(self._path)
        if not path.exists():
            raise FileNotFoundError(f"Semantic model not found: {self._path}")
        with open(path, "r", encoding="utf-8") as f:
            self._raw = yaml.safe_load(f)
        model_info = self._raw.get("model", {})
        self.name = model_info.get("name", "unknown")
        self.description = model_info.get("description", "")
        self.timezone = model_info.get("timezone", "UTC")
        self.currency = model_info.get("currency", "USD")
        logging.info(
            f"[SemanticModel] Loaded '{self.name}' from {self._path} "
            f"({len(self._raw.get('tables', {}))} tables)"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Core accessors — return data in the same shape as the old hardcoded dicts
    # ═══════════════════════════════════════════════════════════════════════

    def get_table_metadata(self) -> dict[str, dict]:
        """
        Return TABLE_METADATA in the exact shape the pipeline expects:

        {
          'TableName': {
            'columns': {'col_name': 'description', ...},
            'time_column': 'col' | None,
            'default_filters': [],
            'notes': '...',
          },
          ...
        }
        """
        tables = self._raw.get("tables", {})
        result: dict[str, dict] = {}
        for table_name, table_def in tables.items():
            columns: dict[str, str] = {}
            for col_name, col_info in table_def.get("columns", {}).items():
                if isinstance(col_info, dict):
                    columns[col_name] = col_info.get("description", "")
                else:
                    # Simple string value
                    columns[col_name] = str(col_info)

            time_column = table_def.get("time_column")
            # YAML null → Python None, but string "null" should also be None
            if time_column == "null" or time_column is None:
                time_column = None

            result[table_name] = {
                "columns": columns,
                "time_column": time_column,
                "default_filters": table_def.get("default_filters", []),
                "notes": table_def.get("notes", ""),
            }
        return result

    def get_intent_category_map(self) -> dict[str, str]:
        """
        Return INTENT_CATEGORY_TABLE_MAP:
        {'daily_metrics': 'DailyPerformanceSummary', ...}
        """
        tables = self._raw.get("tables", {})
        result: dict[str, str] = {}
        for table_name, table_def in tables.items():
            cat = table_def.get("intent_category")
            if cat:
                result[cat] = table_name
        return result

    def get_column_corrections(self, table_name: str | None = None) -> dict:
        """
        Return column corrections.

        If table_name is given, return corrections for that table only.
        Otherwise, return the full dict: {'TableName': {'wrong': 'right', ...}}.
        """
        tables = self._raw.get("tables", {})
        if table_name:
            table_def = tables.get(table_name, {})
            return dict(table_def.get("column_corrections", {}))

        result: dict[str, dict] = {}
        for tname, tdef in tables.items():
            corrections = tdef.get("column_corrections", {})
            if corrections:
                result[tname] = dict(corrections)
        return result

    def get_routing_examples(self) -> dict[str, list[str]]:
        """
        Return routing examples per table:
        {'DailyPerformanceSummary': ['show me visits...', ...], ...}
        """
        tables = self._raw.get("tables", {})
        result: dict[str, list[str]] = {}
        for table_name, table_def in tables.items():
            examples = table_def.get("routing_examples", [])
            if examples:
                result[table_name] = list(examples)
        return result

    def get_few_shot_examples(self, table_name: str | None = None) -> dict[str, str] | str:
        """
        Return few-shot SQL examples.

        If table_name is given, return the examples string for that table.
        Otherwise, return the full dict: {'TableName': '...examples...'}.
        """
        tables = self._raw.get("tables", {})
        if table_name:
            table_def = tables.get(table_name, {})
            return table_def.get("few_shot_examples", "")

        result: dict[str, str] = {}
        for tname, tdef in tables.items():
            examples = tdef.get("few_shot_examples", "")
            if examples:
                result[tname] = examples
        return result

    def get_table_relationships(self) -> dict[str, dict]:
        """
        Return table relationships from YAML:
        {
          'DailyPerformanceSummary': {
            'cannot_combine_with': ['CustomerSummary', ...],
            'shares_dimension': {'GeographicPerformanceSummary': ['idBranch'], ...}
          }, ...
        }
        """
        return dict(self._raw.get("relationships", {}))

    def get_column_groups(self, table_name: str) -> dict[str, list[str]]:
        """Return column_groups for a table: {'visits': ['daily_visits', ...], ...}"""
        tables = self._raw.get("tables", {})
        table_def = tables.get(table_name, {})
        return dict(table_def.get("column_groups", {}))

    def get_verified_queries(self) -> list[dict]:
        """Return the verified_queries list from YAML."""
        return list(self._raw.get("verified_queries", []))

    def get_terminology(self) -> dict:
        """Return the full terminology section."""
        return self._raw.get("terminology", {})

    def get_table_names(self) -> list[str]:
        """Return all table names."""
        return list(self._raw.get("tables", {}).keys())

    def get_intent_categories(self) -> list[str]:
        """Return all intent category values (for building Literal types)."""
        return list(self.get_intent_category_map().keys())

    # ═══════════════════════════════════════════════════════════════════════
    # Prompt generation — for dynamic system prompt (Phase 4)
    # ═══════════════════════════════════════════════════════════════════════

    def generate_intent_descriptions(self) -> str:
        """
        Generate the intent_category description block for the main agent prompt.

        Returns something like:
          - daily_metrics: Daily visits, revenue, orders — supports date filtering
          - monthly_metrics: Monthly trends, year-over-year...
        """
        tables = self._raw.get("tables", {})
        lines = []
        for table_name, table_def in tables.items():
            cat = table_def.get("intent_category")
            desc = table_def.get("description", "")
            if cat:
                time_note = ""
                tc = table_def.get("time_column")
                if tc and tc != "null":
                    time_note = " (supports date filtering)"
                else:
                    time_note = " (lifetime only)"
                lines.append(f"  - {cat}: {desc}{time_note}")
        return "\n".join(lines)

    def generate_terminology_prompt(self) -> str:
        """
        Generate the terminology section for the main agent prompt.
        """
        terminology = self.get_terminology()
        if not terminology:
            return ""

        lines = ["**Terminology:**"]

        segments = terminology.get("segments", {})
        if segments:
            lines.append("Loyalty Segments:")
            for seg_id, seg_info in segments.items():
                name = seg_info.get("name", seg_id)
                defn = seg_info.get("definition", "")
                lines.append(f"  - {name}: {defn}")

        reward_types = terminology.get("reward_types", {})
        if reward_types:
            lines.append("Reward Types:")
            for rtype, rdesc in reward_types.items():
                lines.append(f"  - {rtype.title()}: {rdesc}")

        return "\n".join(lines)

    def generate_arabic_dictionary_prompt(self) -> str:
        """
        Generate the Arabic dictionary section — only injected when Arabic is detected.
        """
        terminology = self.get_terminology()
        arabic_dict = terminology.get("arabic_dictionary", {})
        if not arabic_dict:
            return ""

        lines = ["**Arabic Dictionary (Arabic → English concept → Table):**"]
        for term, info in arabic_dict.items():
            if isinstance(info, dict):
                english = info.get("english", "")
                table = info.get("table", "")
                notes = info.get("notes", "")
                entry = f"  - {term} → {english}"
                if table:
                    entry += f" [{table}]"
                if notes:
                    entry += f" — {notes}"
                lines.append(entry)

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton — initialized once, reused across all requests
# ═══════════════════════════════════════════════════════════════════════════════

_semantic_model: SemanticModel | None = None

# Default path: semantic_models/bonat.yaml relative to project root
_DEFAULT_YAML_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "semantic_models",
    "bonat.yaml",
)

SEMANTIC_MODEL_PATH = os.getenv("SEMANTIC_MODEL_PATH", _DEFAULT_YAML_PATH)


def get_semantic_model() -> SemanticModel:
    """Get or create the singleton SemanticModel instance."""
    global _semantic_model
    if _semantic_model is None:
        _semantic_model = SemanticModel(SEMANTIC_MODEL_PATH)
    return _semantic_model
