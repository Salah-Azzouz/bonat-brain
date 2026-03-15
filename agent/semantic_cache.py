"""
Semantic Cache — In-memory cache with semantic similarity matching.

Eliminates nondeterminism for repeat/similar questions from the same merchant.
Uses cosine similarity on embeddings to match semantically equivalent questions.

Key: (question_embedding, merchant_id, date_bucket)
Value: (response_dict, timestamp)

Inspired by AWS Bedrock's semantic caching pattern.
"""

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

SIMILARITY_THRESHOLD = 0.95   # Very strict — only near-exact matches
MAX_CACHE_SIZE = 1000          # LRU eviction after this
TTL_TIME_SENSITIVE = 3600      # 1 hour for queries with time filters
TTL_TIMELESS = 86400           # 24 hours for lifetime queries


@dataclass
class CacheEntry:
    """A cached pipeline result."""
    question: str
    merchant_id: str
    date_bucket: str
    embedding: list[float]
    result: dict
    timestamp: float
    ttl: int
    has_time_filter: bool

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.timestamp) > self.ttl


@dataclass
class CacheHit:
    """A cache hit result returned to the caller."""
    result: dict
    score: float
    cached_question: str


class SemanticCache:
    """
    In-memory semantic cache for pipeline results.

    Thread-safe enough for our use case (FastAPI async with single worker).
    For multi-worker, would need Redis or shared memory.
    """

    def __init__(self) -> None:
        self._entries: list[CacheEntry] = []
        self._embeddings_model = None
        self._initialized = False
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the embeddings model."""
        try:
            from langchain_openai import OpenAIEmbeddings
            self._embeddings_model = OpenAIEmbeddings(model="text-embedding-3-large")
            self._initialized = True
            logger.info("[SemanticCache] Initialized")
        except Exception as e:
            logger.warning(f"[SemanticCache] Failed to initialize (will run in no-op mode): {e}")
            self._initialized = False

    def get(self, question: str, merchant_id: str) -> Optional[CacheHit]:
        """
        Look up a semantically similar cached result.

        Args:
            question: The user's question
            merchant_id: The merchant's ID

        Returns:
            CacheHit if found, None otherwise
        """
        if not self._initialized:
            return None

        try:
            q_embedding = self._embeddings_model.embed_query(question)
        except Exception as e:
            logger.debug(f"[SemanticCache] Embedding failed: {e}")
            return None

        today = date.today().isoformat()
        best_hit: Optional[CacheHit] = None
        best_score = 0.0

        # Clean expired entries while searching
        active_entries = []
        for entry in self._entries:
            if entry.is_expired:
                continue
            active_entries.append(entry)

            # Must be same merchant
            if entry.merchant_id != str(merchant_id):
                continue

            # For time-sensitive queries, must be same date bucket
            if entry.has_time_filter and entry.date_bucket != today:
                continue

            # Compute cosine similarity
            score = self._cosine_similarity(q_embedding, entry.embedding)
            if score >= SIMILARITY_THRESHOLD and score > best_score:
                best_score = score
                best_hit = CacheHit(
                    result=entry.result,
                    score=score,
                    cached_question=entry.question,
                )

        self._entries = active_entries

        if best_hit:
            logger.info(
                f"[SemanticCache] HIT: score={best_hit.score:.3f}, "
                f"cached='{best_hit.cached_question[:60]}'"
            )
        return best_hit

    def put(
        self,
        question: str,
        merchant_id: str,
        result: dict,
        has_time_filter: bool = False,
    ) -> None:
        """
        Cache a pipeline result.

        Args:
            question: The user's question
            merchant_id: The merchant's ID
            result: The full pipeline response dict
            has_time_filter: Whether the query used time filtering
        """
        if not self._initialized:
            return

        try:
            q_embedding = self._embeddings_model.embed_query(question)
        except Exception as e:
            logger.debug(f"[SemanticCache] Embedding failed for put: {e}")
            return

        ttl = TTL_TIME_SENSITIVE if has_time_filter else TTL_TIMELESS

        entry = CacheEntry(
            question=question[:500],
            merchant_id=str(merchant_id),
            date_bucket=date.today().isoformat(),
            embedding=q_embedding,
            result=result,
            timestamp=time.time(),
            ttl=ttl,
            has_time_filter=has_time_filter,
        )

        # LRU eviction if at capacity
        if len(self._entries) >= MAX_CACHE_SIZE:
            # Remove oldest entry
            self._entries.sort(key=lambda e: e.timestamp)
            self._entries = self._entries[1:]

        self._entries.append(entry)
        logger.info(
            f"[SemanticCache] PUT: '{question[:60]}' "
            f"(merchant={merchant_id}, ttl={ttl}s)"
        )

    def invalidate(self, merchant_id: str) -> int:
        """
        Invalidate all cached entries for a merchant.
        Call this when merchant data is refreshed.

        Returns number of entries removed.
        """
        before = len(self._entries)
        self._entries = [
            e for e in self._entries
            if e.merchant_id != str(merchant_id)
        ]
        removed = before - len(self._entries)
        if removed:
            logger.info(f"[SemanticCache] Invalidated {removed} entries for merchant {merchant_id}")
        return removed

    @property
    def size(self) -> int:
        """Number of entries currently in cache."""
        return len(self._entries)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_semantic_cache: SemanticCache | None = None


def get_semantic_cache() -> SemanticCache:
    """Get or create the singleton SemanticCache instance."""
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = SemanticCache()
    return _semantic_cache
