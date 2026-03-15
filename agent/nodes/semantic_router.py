"""
Semantic Router — Embedding-based table selection (Layer 2).

Routes user questions to the correct database table by comparing
embedding similarity against pre-defined example utterances per table.

This sits between the deterministic regex router (Layer 1) and
intent_category fallback (Layer 3) in the routing stack:

  1. Deterministic regex  (fastest, highest confidence)
  2. Semantic router      (THIS — embedding similarity, ~50-100ms)
  3. intent_category      (main agent's enum classification)
  4. LLM fallback         (expensive, edge cases)

Why embeddings instead of keywords?
  - Immune to reformulation drift (matches meaning, not surface form)
  - Handles Arabic + English naturally (multilingual embeddings)
  - No LLM call needed — just a single embed + dot product
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from langchain_openai import OpenAIEmbeddings


# ═══════════════════════════════════════════════════════════════════════════════
# Route Definitions — Example utterances per table
# ═══════════════════════════════════════════════════════════════════════════════
# Each table gets 5-8 representative utterances (English + Arabic).
# These are embedded once at startup and cached in memory.

# ── Load routing examples from YAML semantic model ──
from agent.semantic_model import get_semantic_model as _get_semantic_model
TABLE_ROUTES: dict[str, list[str]] = _get_semantic_model().get_routing_examples()


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Router Class
# ═══════════════════════════════════════════════════════════════════════════════

class SemanticRouter:
    """
    Embedding-based question-to-table router.

    At init: embeds all example utterances (one batch API call).
    At query time: embeds the question, computes cosine similarity
    against all cached vectors, returns the best-matching table.
    """

    def __init__(self) -> None:
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        self._route_vectors: dict[str, np.ndarray] = {}
        self._table_names: list[str] = []
        self._build_routes()

    def _build_routes(self) -> None:
        """Embed all utterances at startup (single batch call)."""
        all_utterances: list[str] = []
        table_labels: list[str] = []

        for table, utterances in TABLE_ROUTES.items():
            all_utterances.extend(utterances)
            table_labels.extend([table] * len(utterances))

        logging.info(f"[SemanticRouter] Embedding {len(all_utterances)} route utterances...")
        all_vectors = self.embeddings.embed_documents(all_utterances)

        # Group vectors by table and pre-normalize for fast cosine similarity
        for table in TABLE_ROUTES:
            self._table_names.append(table)
            vecs = np.array([
                vec for vec, label in zip(all_vectors, table_labels) if label == table
            ], dtype=np.float32)
            # Pre-normalize: cosine_sim = dot(normalized_a, normalized_b)
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-10)  # avoid divide-by-zero
            self._route_vectors[table] = vecs / norms

        logging.info(f"[SemanticRouter] Initialized with {len(TABLE_ROUTES)} routes, "
                      f"{len(all_utterances)} utterances")

    def route(self, question: str, threshold: float = 0.75) -> tuple[Optional[str], float]:
        """
        Find the best matching table by cosine similarity.

        Args:
            question: The user's question to route.
            threshold: Minimum similarity score to return a match.

        Returns:
            (table_name, confidence) if similarity >= threshold,
            (None, best_score) otherwise.
        """
        q_vector = np.array(self.embeddings.embed_query(question), dtype=np.float32)
        q_norm = np.linalg.norm(q_vector)
        if q_norm > 0:
            q_vector = q_vector / q_norm

        best_table: Optional[str] = None
        best_score: float = 0.0

        for table, vectors in self._route_vectors.items():
            # Cosine similarity via dot product (both sides pre-normalized)
            similarities = vectors @ q_vector
            max_sim = float(similarities.max())
            if max_sim > best_score:
                best_score = max_sim
                best_table = table

        if best_score >= threshold:
            return best_table, best_score
        return None, best_score


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton — initialized once, reused across all requests
# ═══════════════════════════════════════════════════════════════════════════════

_router: Optional[SemanticRouter] = None


def get_semantic_router() -> SemanticRouter:
    """Get or create the singleton SemanticRouter instance."""
    global _router
    if _router is None:
        _router = SemanticRouter()
    return _router
