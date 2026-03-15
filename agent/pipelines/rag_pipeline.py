"""
Agentic RAG Pipeline

This module implements an intelligent RAG (Retrieval-Augmented Generation) system
that can answer questions about Bonat features, best practices, and how-to guides.

The pipeline is "agentic" because it:
1. Reformulates queries for better retrieval
2. Evaluates retrieval quality
3. Re-retrieves if needed
4. Generates grounded answers
5. Self-validates responses
"""

import logging
import os
from typing import Dict, List, Optional
from langchain_qdrant import QdrantVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

# Try to import BM25 for hybrid search (optional)
try:
    from rank_bm25 import BM25Okapi
    import numpy as np
    BM25_AVAILABLE = True
except ImportError:
    logging.warning("[Agentic RAG] rank-bm25 not installed, hybrid search disabled")
    BM25_AVAILABLE = False
    BM25Okapi = None
    np = None


class AgenticRAG:
    """
    Agentic RAG system for Bonat knowledge base.
    """

    def __init__(self, collection_name: str = "bonat_strategy"):
        """
        Initialize the Agentic RAG system.

        Args:
            collection_name: Name of the Qdrant collection to use
        """
        self.collection_name = collection_name
        self.qdrant_host = os.getenv("QDRANT_HOST", "51.44.2.49")
        self.qdrant_port = int(os.getenv("QDRANT_PORT", "443"))
        self.qdrant_api_key = os.getenv("QDRANT__SERVICE__API_KEY", "")


        # Initialize embeddings (same as indexing to ensure consistency)
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-large"
        )

        # Initialize Qdrant client
        self.qdrant_client = QdrantClient(
            host=self.qdrant_host,
            port=self.qdrant_port,
            api_key=self.qdrant_api_key,
            https=True,
            verify=False,
            timeout=60,
            prefer_grpc=False
        )

        # Connect to vector store
        try:
            self.vectorstore = QdrantVectorStore(
                client=self.qdrant_client,
                embedding=self.embeddings,
                collection_name=self.collection_name,
            )
            logging.info(f"[Agentic RAG] Connected to Qdrant collection: {collection_name}")
        except Exception as e:
            logging.error(f"[Agentic RAG] Failed to connect to Qdrant: {e}")
            self.vectorstore = None

        # Initialize BM25 index for hybrid search
        self.bm25_index = None
        self.bm25_corpus = []
        self.bm25_documents = []
        self._initialize_bm25()

    def _initialize_bm25(self):
        """
        Initialize BM25 index by loading all documents from Qdrant.
        This enables keyword-based search alongside semantic search.
        """
        if not BM25_AVAILABLE:
            logging.info("[Agentic RAG] BM25 not available, skipping initialization")
            self.bm25_index = None
            return

        try:
            logging.info("[Agentic RAG] Initializing BM25 index for hybrid search...")

            # Fetch all documents from Qdrant
            points, _ = self.qdrant_client.scroll(
                collection_name=self.collection_name,
                limit=1000,  # Adjust based on collection size
                with_payload=True,
                with_vectors=False
            )

            # Extract content and metadata
            for point in points:
                content = point.payload.get('page_content', '')
                metadata = point.payload.get('metadata', {})

                self.bm25_documents.append({
                    'content': content,
                    'metadata': metadata,
                    'id': point.id
                })

                # Tokenize content for BM25 (simple whitespace + lowercase)
                tokenized = content.lower().split()
                self.bm25_corpus.append(tokenized)

            # Build BM25 index
            if self.bm25_corpus:
                self.bm25_index = BM25Okapi(self.bm25_corpus)
                logging.info(f"[Agentic RAG] BM25 index built with {len(self.bm25_corpus)} documents")
            else:
                logging.warning("[Agentic RAG] No documents found for BM25 index")

        except Exception as e:
            logging.error(f"[Agentic RAG] Failed to initialize BM25: {e}")
            self.bm25_index = None

    def _bm25_search(self, query: str, k: int = 10, metadata_filter: Optional[Dict[str, str]] = None) -> List[Dict]:
        """
        Perform BM25 keyword search.

        Args:
            query: Search query
            k: Number of results to return
            metadata_filter: Optional metadata filter

        Returns:
            List of documents with BM25 scores
        """
        if not self.bm25_index:
            logging.warning("[Agentic RAG] BM25 index not available")
            return []

        # Tokenize query
        tokenized_query = query.lower().split()

        # Get BM25 scores
        scores = self.bm25_index.get_scores(tokenized_query)

        # Get top k indices
        top_indices = np.argsort(scores)[::-1][:k * 3]  # Get more for filtering

        # Build results with filtering
        results = []
        for idx in top_indices:
            if scores[idx] > 0:  # Only include non-zero scores
                doc = self.bm25_documents[idx]

                # Apply metadata filter if provided
                if metadata_filter:
                    matches = all(
                        doc['metadata'].get(key) == value
                        for key, value in metadata_filter.items()
                    )
                    if not matches:
                        continue

                results.append({
                    'content': doc['content'],
                    'metadata': doc['metadata'],
                    'score': float(scores[idx]),
                    'search_type': 'bm25'
                })

                if len(results) >= k:
                    break

        return results

    def _reciprocal_rank_fusion(
        self,
        vector_results: List[Dict],
        bm25_results: List[Dict],
        k: int = 5,
        k_constant: int = 60
    ) -> List[Dict]:
        """
        Combine vector and BM25 results using Reciprocal Rank Fusion (RRF).

        RRF formula: score(d) = Σ(1 / (k + rank(d)))
        where k is a constant (typically 60) and rank is the position in the result list.

        Args:
            vector_results: Results from vector search
            bm25_results: Results from BM25 search
            k: Number of final results to return
            k_constant: RRF constant (default 60)

        Returns:
            Fused and re-ranked results
        """
        logging.info(f"[Agentic RAG] Fusing {len(vector_results)} vector + {len(bm25_results)} BM25 results")

        # Build RRF scores
        rrf_scores = {}

        # Add vector search scores
        for rank, doc in enumerate(vector_results):
            # Use content as key (assuming unique chunks)
            key = doc['content'][:100]  # First 100 chars as key
            rrf_scores[key] = {
                'score': 1.0 / (k_constant + rank + 1),
                'doc': doc,
                'sources': ['vector']
            }

        # Add BM25 scores
        for rank, doc in enumerate(bm25_results):
            key = doc['content'][:100]
            if key in rrf_scores:
                # Document found in both - boost score
                rrf_scores[key]['score'] += 1.0 / (k_constant + rank + 1)
                rrf_scores[key]['sources'].append('bm25')
            else:
                rrf_scores[key] = {
                    'score': 1.0 / (k_constant + rank + 1),
                    'doc': doc,
                    'sources': ['bm25']
                }

        # Sort by RRF score
        sorted_results = sorted(
            rrf_scores.values(),
            key=lambda x: x['score'],
            reverse=True
        )

        # Return top k with RRF scores
        final_results = []
        for item in sorted_results[:k]:
            doc = item['doc'].copy()
            doc['rrf_score'] = item['score']
            doc['sources'] = item['sources']
            final_results.append(doc)

        logging.info(f"[Agentic RAG] RRF fusion complete, returning {len(final_results)} results")
        return final_results

    def reformulate_query(self, question: str, llm) -> str:
        """
        Step 1: Reformulate the user's question for better retrieval.

        Agentic behavior: The system thinks about how to phrase the query
        to get better results from the vector database.

        Args:
            question: Original user question
            llm: Language model for query reformulation

        Returns:
            Reformulated query optimized for retrieval
        """
        logging.info(f"[Agentic RAG] Reformulating query: {question}")

        reformulation_prompt = ChatPromptTemplate.from_template(
            """Reformulate this question for semantic search in a Bonat loyalty platform knowledge base.
Expand abbreviations, add loyalty-specific keywords, keep to 1-2 sentences.

Question: "{question}"

Reformulated:"""
        )

        chain = reformulation_prompt | llm | StrOutputParser()

        try:
            reformulated = chain.invoke({"question": question})
            logging.info(f"[Agentic RAG] Reformulated to: {reformulated}")
            return reformulated.strip()
        except Exception as e:
            logging.error(f"[Agentic RAG] Query reformulation failed: {e}")
            # Fallback to original question
            return question

    def retrieve_documents(
        self,
        query: str,
        k: int = 5,
        max_distance: float = 0.8,
        use_reranking: bool = True,
        use_hybrid: bool = True,
        metadata_filter: Optional[Dict[str, str]] = None
    ) -> List[Dict]:
        """
        Step 2: Retrieve relevant documents using hybrid search (semantic + keyword).

        Args:
            query: Search query (possibly reformulated)
            k: Number of final documents to return
            max_distance: Maximum cosine distance threshold (0.0-2.0, lower=better) to filter low-quality results
                         Default 0.8 keeps good matches, filters poor ones
            use_reranking: If True, retrieve k*2 candidates and re-rank with LLM to get top k
            use_hybrid: If True, combine vector and BM25 search using RRF (default: True)
            metadata_filter: Optional dict of metadata filters (e.g., {"doc_category": "strategy"})

        Returns:
            List of retrieved documents with content and metadata (only those below distance threshold)
        """
        if not self.vectorstore:
            logging.error("[Agentic RAG] Vector store not available")
            return []

        try:
            # If re-ranking enabled, get more candidates (k*2) to re-rank
            retrieval_k = k * 2 if use_reranking else k

            # Build metadata filter if provided
            # Note: LangChain stores metadata nested under 'metadata' key in Qdrant
            qdrant_filter = None
            if metadata_filter:
                filter_conditions = []
                for key, value in metadata_filter.items():
                    # Prefix with 'metadata.' for LangChain's nested structure
                    filter_conditions.append(
                        FieldCondition(key=f"metadata.{key}", match=MatchValue(value=value))
                    )
                qdrant_filter = Filter(must=filter_conditions)
                logging.info(f"[Agentic RAG] Applying metadata filter: {metadata_filter}")

            if use_hybrid and self.bm25_index:
                # HYBRID SEARCH: Combine MMR (vector with diversity) + BM25 using RRF
                logging.info(f"[Agentic RAG] Using hybrid search (MMR + BM25) for: {query}")

                # 1. MMR search (diversity-aware vector search)
                if qdrant_filter:
                    vector_docs = self.vectorstore.max_marginal_relevance_search(
                        query,
                        k=retrieval_k,
                        fetch_k=retrieval_k * 3,  # Fetch 3x candidates for MMR
                        lambda_mult=0.5,  # Balance relevance (1.0) vs diversity (0.0)
                        filter=qdrant_filter
                    )
                else:
                    vector_docs = self.vectorstore.max_marginal_relevance_search(
                        query,
                        k=retrieval_k,
                        fetch_k=retrieval_k * 3,
                        lambda_mult=0.5
                    )

                # Convert to dict format (MMR doesn't return scores, use rank-based)
                vector_candidates = []
                for rank, doc in enumerate(vector_docs):
                    vector_candidates.append({
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": 1.0 / (rank + 1),  # Rank-based score
                        "search_type": "mmr"
                    })

                # 2. BM25 search
                bm25_candidates = self._bm25_search(query, k=retrieval_k, metadata_filter=metadata_filter)

                # 3. Fuse results with RRF
                candidates = self._reciprocal_rank_fusion(
                    vector_candidates,
                    bm25_candidates,
                    k=retrieval_k
                )

                logging.info(f"[Agentic RAG] Hybrid search (MMR+BM25) returned {len(candidates)} fused candidates")

            else:
                # MMR-ONLY SEARCH (fallback if BM25 not available or disabled)
                logging.info(f"[Agentic RAG] Using MMR search for: {query}")

                if qdrant_filter:
                    docs = self.vectorstore.max_marginal_relevance_search(
                        query,
                        k=retrieval_k,
                        fetch_k=retrieval_k * 3,
                        lambda_mult=0.5,
                        filter=qdrant_filter
                    )
                else:
                    docs = self.vectorstore.max_marginal_relevance_search(
                        query,
                        k=retrieval_k,
                        fetch_k=retrieval_k * 3,
                        lambda_mult=0.5
                    )

                # Convert to candidates (rank-based scoring)
                candidates = []
                for rank, doc in enumerate(docs):
                    candidates.append({
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": 1.0 / (rank + 1)
                    })

                logging.info(f"[Agentic RAG] MMR search returned {len(candidates)} candidates")

            # If re-ranking enabled and we have enough candidates, use LLM to re-rank
            if use_reranking and len(candidates) > k:
                from agent.config import get_llm
                logging.info(f"[Agentic RAG] Re-ranking {len(candidates)} candidates to top {k}")
                reranked = self._rerank_with_llm(query, candidates, k, get_llm())
                logging.info(f"[Agentic RAG] Re-ranking complete, returning top {len(reranked)} documents")
                return reranked

            # Otherwise return all candidates (or top k if more than k)
            return candidates[:k]

        except Exception as e:
            logging.error(f"[Agentic RAG] Document retrieval failed: {e}")
            return []

    def _rerank_with_llm(self, question: str, candidates: List[Dict], top_k: int, llm) -> List[Dict]:
        """
        Re-rank candidate documents using LLM for semantic relevance.

        This addresses the limitation of pure vector similarity by having an LLM
        judge which documents are truly most relevant to answering the question.

        Args:
            question: Original user question
            candidates: List of candidate documents from vector search
            top_k: Number of top documents to return after re-ranking
            llm: Language model for re-ranking

        Returns:
            Top K documents after LLM re-ranking
        """
        logging.info(f"[Agentic RAG] LLM re-ranking {len(candidates)} candidates")

        # Prepare documents for LLM evaluation
        docs_text = ""
        for i, doc in enumerate(candidates):
            docs_text += f"\n--- Document {i+1} (Distance: {doc['score']:.3f}) ---\n"
            docs_text += doc['content'][:500]  # First 500 chars to keep prompt manageable
            docs_text += "\n"

        rerank_prompt = ChatPromptTemplate.from_template(
            """Score each document's relevance to the question (0-10). Return JSON array only.

**Question:** {question}

**Documents:**
{documents}

**Return format:** `[{{"doc_index": 1, "score": 9.5, "reason": "brief"}}, ...]`

JSON:"""
        )

        chain = rerank_prompt | llm | StrOutputParser()

        try:
            result = chain.invoke({
                "question": question,
                "documents": docs_text
            })

            logging.info(f"[Agentic RAG] LLM re-ranking response: {result[:200]}...")

            # Parse JSON response
            import json
            # Clean up response - sometimes LLM adds markdown code blocks
            cleaned_result = result.strip()
            if cleaned_result.startswith("```json"):
                cleaned_result = cleaned_result[7:]
            if cleaned_result.startswith("```"):
                cleaned_result = cleaned_result[3:]
            if cleaned_result.endswith("```"):
                cleaned_result = cleaned_result[:-3]
            cleaned_result = cleaned_result.strip()

            scores = json.loads(cleaned_result)

            # Sort candidates by LLM scores
            for score_obj in scores:
                idx = score_obj["doc_index"] - 1  # Convert 1-indexed to 0-indexed
                if 0 <= idx < len(candidates):
                    candidates[idx]["llm_relevance_score"] = score_obj["score"]
                    candidates[idx]["llm_reason"] = score_obj.get("reason", "")

            # Sort by LLM score (highest first)
            reranked = sorted(
                [c for c in candidates if "llm_relevance_score" in c],
                key=lambda x: x["llm_relevance_score"],
                reverse=True
            )

            logging.info(f"[Agentic RAG] Re-ranked {len(reranked)} documents, returning top {top_k}")
            return reranked[:top_k]

        except Exception as e:
            logging.error(f"[Agentic RAG] Re-ranking failed: {e}, falling back to vector scores")
            # Fallback: return top k by vector distance (lower = better)
            return sorted(candidates, key=lambda x: x["score"])[:top_k]

    def evaluate_retrieval_quality(self, question: str, documents: List[Dict], llm) -> Dict:
        """
        Step 3: Evaluate if retrieved documents are good enough to answer the question.

        Agentic behavior: The system self-assesses whether it has enough information.

        Args:
            question: Original user question
            documents: Retrieved documents
            llm: Language model for evaluation

        Returns:
            Dict with quality assessment and feedback
        """
        logging.info("[Agentic RAG] Evaluating retrieval quality...")

        if not documents:
            return {
                "is_sufficient": False,
                "confidence": 0.0,
                "feedback": "No documents retrieved"
            }

        # Combine document contents for evaluation
        context = "\n\n".join([f"Document {i+1}:\n{doc['content'][:500]}..."
                               for i, doc in enumerate(documents[:3])])

        evaluation_prompt = ChatPromptTemplate.from_template(
            """Are these documents relevant and helpful for the question? Be lenient — related content counts.

**Question:** "{question}"

**Context:**
{context}

**Return JSON only:**
{{
    "is_sufficient": true/false,
    "confidence": 0.0-1.0,
    "feedback": "brief explanation"
}}"""
        )

        chain = evaluation_prompt | llm | StrOutputParser()

        try:
            result = chain.invoke({"question": question, "context": context})

            # Parse JSON response
            import json
            evaluation = json.loads(result.strip())

            logging.info(f"[Agentic RAG] Quality evaluation: {evaluation}")
            return evaluation

        except Exception as e:
            logging.error(f"[Agentic RAG] Quality evaluation failed: {e}")
            # Default to accepting retrieval
            return {
                "is_sufficient": True,
                "confidence": 0.7,
                "feedback": "Evaluation failed, proceeding with retrieved documents"
            }

    def generate_answer(self, question: str, documents: List[Dict], llm) -> Dict:
        """
        Step 4: Generate a grounded answer based on retrieved documents.

        Args:
            question: Original user question
            documents: Retrieved documents
            llm: Language model for answer generation

        Returns:
            Dict with generated answer and sources
        """
        logging.info("[Agentic RAG] Generating answer from documents...")

        if not documents:
            return {
                "answer": "I don't have enough information in my knowledge base to answer that question. Could you rephrase or ask about a different Bonat topic?",
                "sources": [],
                "confidence": 0.0
            }

        # Prepare context from documents
        context = "\n\n".join([f"[Document {i+1}]\n{doc['content']}"
                              for i, doc in enumerate(documents)])

        generation_prompt = ChatPromptTemplate.from_template(
            """Answer the question using ONLY the provided context. If context has relevant info (even partial), share it. If nothing relevant, say "I don't have specific information about this in the documentation." Do not add advice beyond what's in the context.

**Context:**
{context}

**Question:** {question}

**Answer:**"""
        )

        chain = generation_prompt | llm | StrOutputParser()

        try:
            answer = chain.invoke({"question": question, "context": context})

            # Extract source metadata
            sources = []
            for doc in documents[:3]:  # Top 3 sources
                sources.append({
                    "page": doc["metadata"].get("page", "unknown"),
                    "source": doc["metadata"].get("source", "Bonat documentation"),
                    "relevance": doc.get("relevance_score", 0.0)
                })

            logging.info(f"[Agentic RAG] Answer generated: {answer[:100]}...")

            return {
                "answer": answer.strip(),
                "sources": sources,
                "confidence": 0.9 if documents else 0.3
            }

        except Exception as e:
            logging.error(f"[Agentic RAG] Answer generation failed: {e}")
            return {
                "answer": "I encountered an error generating the answer. Please try rephrasing your question.",
                "sources": [],
                "confidence": 0.0
            }

    def validate_answer(self, question: str, answer: str, documents: List[Dict], llm) -> Dict:
        """
        Step 5: Validate the generated answer for quality and groundedness.

        Agentic behavior: Self-validation before returning to user.

        Args:
            question: Original question
            answer: Generated answer
            documents: Source documents
            llm: Language model for validation

        Returns:
            Dict with validation result
        """
        logging.info("[Agentic RAG] Validating generated answer...")

        validation_prompt = ChatPromptTemplate.from_template(
            """Is this answer grounded in the context and free of hallucinations?

**Question:** "{question}"
**Answer:** "{answer}"
**Context:** "{context}"

**Return JSON only:**
{{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "issues": ["issues if any"],
    "feedback": "brief explanation"
}}"""
        )

        context_summary = "\n".join([doc['content'][:200] for doc in documents[:2]])
        chain = validation_prompt | llm | StrOutputParser()

        try:
            result = chain.invoke({
                "question": question,
                "answer": answer,
                "context": context_summary
            })

            import json
            validation = json.loads(result.strip())

            logging.info(f"[Agentic RAG] Validation result: {validation}")
            return validation

        except Exception as e:
            logging.error(f"[Agentic RAG] Validation failed: {e}")
            # Default to accepting answer
            return {
                "is_valid": True,
                "confidence": 0.7,
                "issues": [],
                "feedback": "Validation check failed, proceeding with answer"
            }


def estimate_query_complexity(query: str) -> int:
    """
    Estimate query complexity and return appropriate K value for retrieval.

    Uses heuristic analysis to determine how many documents are needed:
    - Simple queries (definitions, single facts): K=3
    - Medium queries (explanations, how-to): K=5
    - Complex queries (comparisons, comprehensive overviews): K=10

    Args:
        query: The user's question

    Returns:
        Recommended number of documents to retrieve (K value)
    """
    query_lower = query.lower()
    word_count = len(query.split())

    # Signals indicating complex queries needing more documents
    complex_signals = [
        'compare', 'comparison', 'difference', 'differences', 'versus', 'vs',
        'all', 'everything', 'comprehensive', 'complete', 'full',
        'overview', 'summary of all', 'list all', 'every',
        'pros and cons', 'advantages and disadvantages',
        'best practices', 'strategies', 'approaches'
    ]

    # Signals indicating simple queries needing fewer documents
    simple_signals = [
        'what is', 'what are', 'define', 'definition',
        'who is', 'when did', 'when was', 'where is',
        'is it possible', 'can i', 'how much', 'how many'
    ]

    # Check for complexity indicators
    has_complex_signal = any(signal in query_lower for signal in complex_signals)
    has_simple_signal = any(signal in query_lower for signal in simple_signals)

    # Determine K based on signals and query length
    if has_complex_signal or word_count > 20:
        k = 10  # Complex: need comprehensive context
        complexity = "complex"
    elif has_simple_signal and word_count < 12:
        k = 3   # Simple: focused retrieval
        complexity = "simple"
    else:
        k = 5   # Medium: balanced approach
        complexity = "medium"

    logging.info(f"[Adaptive K] Query complexity: {complexity}, K={k} (word_count={word_count})")
    return k


def execute_agentic_rag(
    question: str,
    merchant_context: Optional[Dict] = None,
    max_retries: int = 2,
    metadata_filter: Optional[Dict[str, str]] = None
) -> str:
    """
    Execute the complete Agentic RAG pipeline.

    This is the main entry point that orchestrates all steps:
    1. Query reformulation
    2. Document retrieval (with optional metadata filtering)
    3. Quality evaluation (with retry if needed)
    4. Answer generation
    5. Answer validation (with retry if needed)

    Args:
        question: User's question
        merchant_context: Optional context about the merchant
        max_retries: Maximum retry attempts if quality is poor
        metadata_filter: Optional dict to filter by metadata (e.g., {"doc_category": "strategy"})

    Returns:
        Final answer as a string

    Examples:
        # No filter - search all documents
        answer = execute_agentic_rag("How do gift campaigns work?")

        # Filter by category
        answer = execute_agentic_rag(
            "Best retention practices?",
            metadata_filter={"doc_category": "strategy"}
        )

        # Filter by content type
        answer = execute_agentic_rag(
            "How to create a campaign?",
            metadata_filter={"content_type": "tutorial"}
        )
    """
    logging.info(f"[Agentic RAG Pipeline] Starting for question: {question}")
    if metadata_filter:
        logging.info(f"[Agentic RAG Pipeline] Metadata filter: {metadata_filter}")

    # Get LLM with callbacks for cost tracking
    from agent.config import get_llm
    llm = get_llm()

    # Initialize RAG system
    rag = AgenticRAG(collection_name="bonat_strategy")

    if not rag.vectorstore:
        logging.error("[Agentic RAG Pipeline] Vector store not available")
        return "I'm sorry, my knowledge base is currently unavailable. Please try again later or contact support."

    reformulated_query = rag.reformulate_query(question, llm)

    # Adaptive K: Dynamically determine number of documents based on query complexity
    adaptive_k = estimate_query_complexity(question)

    documents = []
    retry_count = 0

    while retry_count <= max_retries:
        # Retrieve documents (with optional metadata filter)
        documents = rag.retrieve_documents(
            reformulated_query,
            k=adaptive_k,
            metadata_filter=metadata_filter
        )

        if not documents:
            logging.warning("[Agentic RAG Pipeline] No documents retrieved")
            break

        # Evaluate quality (informational only - we proceed regardless)
        quality = rag.evaluate_retrieval_quality(question, documents, llm)
        logging.info(f"[Agentic RAG Pipeline] Retrieval quality: confidence={quality.get('confidence', 0):.2f}, is_sufficient={quality.get('is_sufficient', False)}")

        # Always proceed with retrieved documents (no quality-based rejection)
        break

    result = rag.generate_answer(question, documents, llm)
    answer = result["answer"]
    sources = result["sources"]

    # Append sources
    if sources:
        answer += f"\n\n📚 Sources: Bonat documentation (pages: {', '.join([str(s.get('page', '?')) for s in sources])})"

    logging.info("[Agentic RAG Pipeline] Pipeline completed successfully")
    return answer
