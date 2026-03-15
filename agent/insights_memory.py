"""
Insights Memory Module - Surfaces Relevant Past Insights

This module embeds AI responses from conversations and enables
semantic search to surface relevant past insights when users ask questions.

Example:
    User asks: "How is my revenue doing?"
    System finds: Past insight from Jan 15 about revenue decline due to campaign ending
    Agent can reference: "Last time you asked about revenue, we found..."
"""

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
import hashlib

# Try to import OpenAI embeddings
try:
    from langchain_openai import OpenAIEmbeddings
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    logging.warning("[Insights Memory] OpenAI embeddings not available")


# Collection name for merchant insights
INSIGHTS_COLLECTION = "merchant_insights"
EMBEDDING_DIMENSION = 3072  # text-embedding-3-large dimension


class InsightsMemory:
    """
    Manages storage and retrieval of past conversation insights.

    Uses Qdrant vector database to store embeddings of AI responses,
    enabling semantic search to find relevant past insights.
    """

    def __init__(self):
        """Initialize connection to Qdrant and embeddings model."""
        self.qdrant_host = os.getenv("QDRANT_HOST", "51.44.2.49")
        self.qdrant_port = int(os.getenv("QDRANT_PORT", "443"))
        self.qdrant_api_key = os.getenv("QDRANT__SERVICE__API_KEY", "")

        self.client = None
        self.embeddings = None
        self._initialized = False

        self._initialize()

    def _initialize(self):
        """Initialize Qdrant client and embeddings."""
        if not EMBEDDINGS_AVAILABLE:
            logging.warning("[Insights Memory] Cannot initialize - embeddings not available")
            return

        try:
            # Initialize embeddings (same model as RAG for consistency)
            self.embeddings = OpenAIEmbeddings(
                model="text-embedding-3-large"
            )

            # Initialize Qdrant client
            self.client = QdrantClient(
                host=self.qdrant_host,
                port=self.qdrant_port,
                api_key=self.qdrant_api_key,
                https=True,
                verify=False,
                timeout=60,
                prefer_grpc=False
            )

            # Ensure collection exists
            self._ensure_collection()
            self._initialized = True
            logging.info("[Insights Memory] Initialized successfully")

        except Exception as e:
            logging.error(f"[Insights Memory] Failed to initialize: {e}")
            self._initialized = False

    def _ensure_collection(self):
        """Create the insights collection if it doesn't exist."""
        try:
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if INSIGHTS_COLLECTION not in collection_names:
                self.client.create_collection(
                    collection_name=INSIGHTS_COLLECTION,
                    vectors_config=VectorParams(
                        size=EMBEDDING_DIMENSION,
                        distance=Distance.COSINE
                    )
                )
                logging.info(f"[Insights Memory] Created collection: {INSIGHTS_COLLECTION}")
            else:
                logging.info(f"[Insights Memory] Collection exists: {INSIGHTS_COLLECTION}")

        except Exception as e:
            logging.error(f"[Insights Memory] Failed to ensure collection: {e}")

    def _generate_point_id(self, message_id: str) -> int:
        """Generate a deterministic numeric ID from message_id string."""
        # Use hash to convert string to numeric ID
        hash_obj = hashlib.md5(message_id.encode())
        # Take first 8 bytes and convert to int (positive)
        return int(hash_obj.hexdigest()[:16], 16) % (2**63)

    def store_insight(
        self,
        message_id: str,
        merchant_id: str,
        user_query: str,
        ai_response: str,
        entities: Dict = None,
        timestamp: datetime = None
    ) -> bool:
        """
        Store an AI response as a searchable insight.

        Args:
            message_id: Unique identifier for the message
            merchant_id: Merchant's ID for filtering
            user_query: The user's original question
            ai_response: The AI's response to embed
            entities: Extracted entities from the conversation
            timestamp: When the conversation happened

        Returns:
            True if stored successfully, False otherwise
        """
        if not self._initialized:
            logging.debug("[Insights Memory] Not initialized, skipping store")
            return False

        # Filter out short or uninformative responses
        if len(ai_response) < 100:
            logging.debug("[Insights Memory] Response too short, skipping")
            return False

        # Skip error responses
        error_indicators = ["sorry", "error", "couldn't", "unable to", "i don't have"]
        if any(indicator in ai_response.lower()[:100] for indicator in error_indicators):
            logging.debug("[Insights Memory] Error response, skipping")
            return False

        try:
            # Create embedding for the AI response
            # We embed both query and response for better matching
            text_to_embed = f"Question: {user_query}\nAnswer: {ai_response[:1000]}"
            embedding = self.embeddings.embed_query(text_to_embed)

            # Prepare metadata
            timestamp = timestamp or datetime.now(timezone.utc)

            payload = {
                "message_id": message_id,
                "merchant_id": merchant_id,
                "user_query": user_query,
                "ai_response": ai_response[:2000],  # Truncate for storage
                "timestamp": timestamp.isoformat(),
                "entities": entities or {},
            }

            # Generate numeric point ID
            point_id = self._generate_point_id(message_id)

            # Store in Qdrant
            self.client.upsert(
                collection_name=INSIGHTS_COLLECTION,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload=payload
                    )
                ]
            )

            logging.info(f"[Insights Memory] Stored insight for message: {message_id[:8]}...")
            return True

        except Exception as e:
            logging.error(f"[Insights Memory] Failed to store insight: {e}")
            return False

    def search_relevant_insights(
        self,
        query: str,
        merchant_id: str,
        limit: int = 3,
        min_score: float = 0.7,
        max_age_days: int = 30
    ) -> List[Dict]:
        """
        Search for relevant past insights based on the current query.

        Args:
            query: The user's current question
            merchant_id: Merchant's ID for filtering
            limit: Maximum number of insights to return
            min_score: Minimum similarity score (0-1)
            max_age_days: Only consider insights from last N days

        Returns:
            List of relevant insights with scores
        """
        if not self._initialized:
            logging.debug("[Insights Memory] Not initialized, returning empty")
            return []

        try:
            # Create embedding for the query
            query_embedding = self.embeddings.embed_query(query)

            # Calculate date cutoff
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

            # Search with merchant filter (using query_points for newer Qdrant API)
            search_result = self.client.query_points(
                collection_name=INSIGHTS_COLLECTION,
                query=query_embedding,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="merchant_id",
                            match=MatchValue(value=merchant_id)
                        )
                    ]
                ),
                limit=limit * 2,  # Fetch more to filter by score and recency
                score_threshold=min_score
            )
            results = search_result.points

            # Process and filter results
            insights = []
            for result in results:
                payload = result.payload

                # Check recency
                insight_time = payload.get("timestamp", "")
                if insight_time < cutoff_date:
                    continue

                # Calculate recency weight (newer = higher weight)
                try:
                    insight_dt = datetime.fromisoformat(insight_time)
                    days_old = (datetime.now(timezone.utc) - insight_dt).days
                    recency_weight = max(0.5, 1.0 - (days_old / max_age_days) * 0.5)
                except (ValueError, TypeError):
                    recency_weight = 0.7

                # Adjusted score
                adjusted_score = result.score * recency_weight

                insights.append({
                    "message_id": payload.get("message_id"),
                    "user_query": payload.get("user_query"),
                    "ai_response": payload.get("ai_response"),
                    "timestamp": insight_time,
                    "entities": payload.get("entities", {}),
                    "raw_score": result.score,
                    "recency_weight": recency_weight,
                    "adjusted_score": adjusted_score
                })

            # Sort by adjusted score and limit
            insights.sort(key=lambda x: x["adjusted_score"], reverse=True)
            insights = insights[:limit]

            if insights:
                logging.info(f"[Insights Memory] Found {len(insights)} relevant insights for merchant {merchant_id}")

            return insights

        except Exception as e:
            logging.error(f"[Insights Memory] Search failed: {e}")
            return []


# Global instance for reuse
_insights_memory = None


def get_insights_memory() -> InsightsMemory:
    """Get or create the global InsightsMemory instance."""
    global _insights_memory
    if _insights_memory is None:
        _insights_memory = InsightsMemory()
    return _insights_memory


def store_conversation_insight(
    message_id: str,
    merchant_id: str,
    user_query: str,
    ai_response: str,
    entities: Dict = None
) -> bool:
    """
    Convenience function to store a conversation insight.

    Called from app.py when saving conversation history.
    """
    memory = get_insights_memory()
    return memory.store_insight(
        message_id=message_id,
        merchant_id=merchant_id,
        user_query=user_query,
        ai_response=ai_response,
        entities=entities
    )


def search_past_insights(
    query: str,
    merchant_id: str,
    limit: int = 2,
    min_score: float = 0.72
) -> List[Dict]:
    """
    Convenience function to search for relevant past insights.

    Called from app.py when preparing agent context.
    """
    memory = get_insights_memory()
    return memory.search_relevant_insights(
        query=query,
        merchant_id=merchant_id,
        limit=limit,
        min_score=min_score
    )


def format_insights_for_prompt(insights: List[Dict], max_length: int = 500) -> str:
    """
    Format past insights for injection into the system prompt.

    Args:
        insights: List of insight dictionaries from search
        max_length: Maximum length per insight summary

    Returns:
        Formatted string for prompt injection
    """
    if not insights:
        return ""

    lines = ["**Relevant Past Insights:**"]

    for i, insight in enumerate(insights, 1):
        # Parse timestamp
        try:
            ts = datetime.fromisoformat(insight["timestamp"])
            date_str = ts.strftime("%b %d")
        except (ValueError, TypeError, KeyError):
            date_str = "Recently"

        # Get the original question and truncated response
        orig_question = insight.get("user_query", "")[:80]
        response_preview = insight.get("ai_response", "")[:max_length]

        # Truncate at last complete sentence if possible
        if len(response_preview) == max_length:
            last_period = response_preview.rfind(". ")
            if last_period > max_length // 2:
                response_preview = response_preview[:last_period + 1]
            else:
                response_preview += "..."

        score = insight.get("adjusted_score", 0)
        lines.append(f"\n[{date_str}] User asked: \"{orig_question}\"")
        lines.append(f"Insight: {response_preview}")

    lines.append("\n*Use these insights to provide continuity and reference past discussions when relevant.*")

    return "\n".join(lines)
