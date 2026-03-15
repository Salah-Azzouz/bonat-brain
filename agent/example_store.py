"""
Example Store — Qdrant-backed verified (question → table, intent) pairs.

This implements the "Function RAG" pattern from Vanna.ai:
  1. Store verified examples of (question → table, intent_json, sql)
  2. At query time, retrieve similar past examples to guide routing & intent
  3. After successful execution, auto-learn new examples (with dedup)

The example store sits between the semantic router (Layer 2) and
intent_category fallback (Layer 4) in the routing stack:

  Layer 1: Deterministic regex     (fastest, highest confidence)
  Layer 2: Semantic router         (embedding similarity, static examples)
  Layer 3: Example store           (THIS — Function RAG, production-learned)
  Layer 4: intent_category         (main agent's enum classification)
  Layer 5: LLM fallback            (expensive, edge cases)

Usage:
    from agent.example_store import get_example_store
    store = get_example_store()
    similar = store.find_similar("how many lost customers?", top_k=3)
    store.add_example("how many lost customers?", "LoyaltyProgramSummary", {...}, "SELECT ...")
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Optional

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from qdrant_client.http.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logging.warning("[ExampleStore] qdrant_client not available")

try:
    from langchain_openai import OpenAIEmbeddings
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    logging.warning("[ExampleStore] OpenAI embeddings not available")


COLLECTION_NAME = "verified_examples"
EMBEDDING_DIMENSION = 3072  # text-embedding-3-large


class ExampleStore:
    """
    Qdrant-backed store of verified (question → table, intent) pairs.

    Follows the same singleton pattern as InsightsMemory (agent/insights_memory.py).
    Reuses the same Qdrant host/port and embedding model.
    """

    def __init__(self) -> None:
        self.client: Optional[QdrantClient] = None
        self.embeddings: Optional[OpenAIEmbeddings] = None
        self._initialized = False
        self._initialize()

    def _initialize(self) -> None:
        """Connect to Qdrant and ensure collection exists."""
        if not QDRANT_AVAILABLE or not EMBEDDINGS_AVAILABLE:
            logging.warning("[ExampleStore] Dependencies not available — running in no-op mode")
            return

        try:
            self.embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

            qdrant_host = os.getenv("QDRANT_HOST", "51.44.2.49")
            qdrant_port = int(os.getenv("QDRANT_PORT", "443"))
            qdrant_api_key = os.getenv("QDRANT__SERVICE__API_KEY", "")

            self.client = QdrantClient(
                host=qdrant_host,
                port=qdrant_port,
                api_key=qdrant_api_key,
                https=True,
                verify=False,
                timeout=60,
                prefer_grpc=False,
            )

            self._ensure_collection()
            self._initialized = True
            logging.info("[ExampleStore] Initialized successfully")

        except Exception as e:
            logging.error(f"[ExampleStore] Failed to initialize: {e}")
            self._initialized = False

    def _ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        try:
            collections = self.client.get_collections().collections
            names = [c.name for c in collections]
            if COLLECTION_NAME not in names:
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=EMBEDDING_DIMENSION,
                        distance=Distance.COSINE,
                    ),
                )
                logging.info(f"[ExampleStore] Created collection: {COLLECTION_NAME}")
            else:
                logging.info(f"[ExampleStore] Collection exists: {COLLECTION_NAME}")
        except Exception as e:
            logging.error(f"[ExampleStore] Failed to ensure collection: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # Query — Find similar verified examples
    # ═══════════════════════════════════════════════════════════════════════

    def find_similar(
        self,
        question: str,
        top_k: int = 3,
        min_score: float = 0.85,
    ) -> list[dict[str, Any]]:
        """
        Retrieve most similar verified examples.

        Args:
            question: The user's question to match against.
            top_k: Maximum number of results.
            min_score: Minimum cosine similarity threshold.

        Returns:
            List of dicts with keys: question, table, intent_json, sql, score.
            Empty list if not initialized or no matches found.
        """
        if not self._initialized:
            return []

        try:
            q_vector = self.embeddings.embed_query(question)
            results = self.client.query_points(
                collection_name=COLLECTION_NAME,
                query=q_vector,
                limit=top_k,
                score_threshold=min_score,
            )

            examples = []
            for point in results.points:
                examples.append({
                    "question": point.payload.get("question", ""),
                    "table": point.payload.get("table", ""),
                    "intent_json": point.payload.get("intent_json", ""),
                    "sql": point.payload.get("sql", ""),
                    "score": point.score,
                })

            if examples:
                logging.info(
                    f"[ExampleStore] Found {len(examples)} similar examples "
                    f"(best: {examples[0]['table']} @ {examples[0]['score']:.3f})"
                )
            return examples

        except Exception as e:
            logging.error(f"[ExampleStore] find_similar failed: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # Store — Add a verified example (with deduplication)
    # ═══════════════════════════════════════════════════════════════════════

    def add_example(
        self,
        question: str,
        table: str,
        intent: dict | None = None,
        sql: str = "",
        quality_score: float | None = None,
    ) -> bool:
        """
        Store a verified example after successful query execution.

        Quality gate (Databricks "Trusted Assets" pattern):
        - If quality_score is provided and < 0.7, skip storage
        - Deduplicates: if cosine similarity > 0.95 to an existing example
          for the same table, skip the insert.

        Args:
            question: The user's original question.
            table: The table that was queried successfully.
            intent: The structured QueryIntent as a dict (optional).
            sql: The SQL that was executed successfully.
            quality_score: 0.0-1.0 quality score from pipeline. None = no gate.

        Returns:
            True if stored, False if skipped (duplicate/low quality) or error.
        """
        if not self._initialized:
            return False

        # Skip very short questions (likely noise)
        if len(question.strip()) < 10:
            return False

        # Quality gate: reject low-quality examples
        if quality_score is not None and quality_score < 0.7:
            logging.info(
                f"[ExampleStore] Quality gate rejected: score={quality_score:.2f} "
                f"for '{question[:60]}'"
            )
            return False

        try:
            q_vector = self.embeddings.embed_query(question)

            # Dedup check: is there already a very similar example for same table?
            existing = self.client.query_points(
                collection_name=COLLECTION_NAME,
                query=q_vector,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="table",
                            match=MatchValue(value=table),
                        )
                    ]
                ),
                limit=1,
                score_threshold=0.95,
            )
            if existing.points:
                logging.debug(
                    f"[ExampleStore] Skipping duplicate (similarity "
                    f"{existing.points[0].score:.3f} to existing)"
                )
                return False

            # Generate deterministic ID from question text
            point_id = self._hash_id(question)

            import json
            self.client.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=q_vector,
                        payload={
                            "question": question[:500],
                            "table": table,
                            "intent_json": json.dumps(intent) if intent else "",
                            "sql": sql[:2000],
                        },
                    )
                ],
            )
            logging.info(f"[ExampleStore] Stored example: '{question[:60]}...' → {table}")
            return True

        except Exception as e:
            logging.error(f"[ExampleStore] add_example failed: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # Seed — Populate from YAML on first startup
    # ═══════════════════════════════════════════════════════════════════════

    def seed_from_yaml(self) -> int:
        """
        One-time seed from YAML routing_examples.
        Runs at startup if collection is empty.

        Returns:
            Number of examples seeded.
        """
        if not self._initialized:
            return 0

        # Skip if collection already has data
        current = self.count()
        if current > 0:
            logging.info(f"[ExampleStore] Already seeded ({current} examples) — skipping")
            return 0

        from agent.semantic_model import get_semantic_model
        model = get_semantic_model()
        routing_examples = model.get_routing_examples()

        seeded = 0
        for table, questions in routing_examples.items():
            for q in questions:
                if self.add_example(question=q, table=table):
                    seeded += 1

        logging.info(f"[ExampleStore] Seeded {seeded} examples from YAML")
        return seeded

    # ═══════════════════════════════════════════════════════════════════════
    # Utilities
    # ═══════════════════════════════════════════════════════════════════════

    def count(self) -> int:
        """Number of examples in the store."""
        if not self._initialized:
            return 0
        try:
            info = self.client.get_collection(COLLECTION_NAME)
            return info.points_count
        except Exception:
            return 0

    @staticmethod
    def _hash_id(text: str) -> int:
        """Generate a deterministic numeric ID from text."""
        h = hashlib.md5(text.encode("utf-8"))
        return int(h.hexdigest()[:16], 16) % (2**63)


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_example_store: ExampleStore | None = None


def get_example_store() -> ExampleStore:
    """Get or create the singleton ExampleStore instance."""
    global _example_store
    if _example_store is None:
        _example_store = ExampleStore()
    return _example_store
