"""
Intelligent Metadata Generation using LLM

This module uses an LLM to analyze document content and generate
meaningful metadata based on the actual content, not just filename.
"""

import logging
from typing import Dict, List
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import json


def generate_metadata_with_llm(
    filename: str,
    sample_content: str,
    llm
) -> Dict[str, str]:
    """
    Use LLM to intelligently analyze document and generate metadata.

    Args:
        filename: Document filename
        sample_content: First ~2000 characters of document for analysis
        llm: Language model for analysis

    Returns:
        Dict with intelligent metadata
    """
    logging.info(f"[LLM Metadata] Analyzing document: {filename}")

    metadata_prompt = ChatPromptTemplate.from_template(
        """You are an expert at analyzing business documents about Bonat, a customer loyalty platform.

**CRITICAL: You must READ and ANALYZE the actual document content below to determine the category, NOT just the filename.**

**Document Filename:** {filename}

**Document Content (READ THIS CAREFULLY):**
{content_sample}

**Your Task:**
Based on the CONTENT above (not just the filename), generate metadata for semantic search.

**Metadata to Generate:**

1. **doc_category** - Read the content and choose ONE that best fits:
   - "strategy": Business strategy, planning, best practices, recommendations
   - "guide": Step-by-step guides, how-to instructions, user manuals
   - "technical": API documentation, technical specs, integration guides
   - "support": FAQs, troubleshooting, problem-solving
   - "reference": Definitions, glossaries, feature lists, specifications
   - "general": Doesn't fit other categories

2. **doc_type** - Based on content structure, choose ONE:
   - "tutorial": Step-by-step instructions
   - "overview": High-level summary or introduction
   - "reference": Detailed specifications or feature list
   - "guide": Comprehensive guide or manual
   - "analysis": Data analysis, insights, or reports

3. **primary_topics** - Extract 3-5 main topics from the content (comma-separated)
   Example: "loyalty programs, customer retention, rewards, gifting, segmentation"

4. **use_cases** - Based on content, what questions would this document answer? (3-5 questions, comma-separated)
   Example: "How to set up rewards?, How to segment customers?, How to improve retention?"

5. **content_summary** - Write ONE sentence summarizing what this document covers

**IMPORTANT:** Base your analysis on the CONTENT, not assumptions from the filename.

**Response Format (JSON only):**
{{
    "doc_category": "strategy",
    "doc_type": "guide",
    "primary_topics": "loyalty programs, customer retention, rewards, gifting",
    "use_cases": "How to set up rewards?, How to improve retention?, How to segment customers?",
    "content_summary": "Comprehensive guide on loyalty program setup and customer retention strategies"
}}

Respond ONLY with valid JSON:"""
    )

    chain = metadata_prompt | llm | StrOutputParser()

    try:
        result = chain.invoke({
            "filename": filename,
            "content_sample": sample_content[:2000]  # First 2000 chars
        })

        # Parse JSON response
        metadata = json.loads(result.strip())
        logging.info(f"[LLM Metadata] Generated: {metadata}")

        return metadata

    except Exception as e:
        logging.error(f"[LLM Metadata] Failed to generate metadata: {e}")
        # Minimal fallback if LLM fails
        return {
            "doc_category": "general",
            "doc_type": "guide",
            "primary_topics": "general topics",
            "use_cases": "general questions",
            "content_summary": f"Document: {filename}"
        }


def extract_section_metadata(chunk_text: str, llm) -> Dict[str, str]:
    """
    Extract section-level metadata for a chunk.

    This identifies what specific topic/section the chunk covers.
    """
    section_prompt = ChatPromptTemplate.from_template(
        """Analyze this text chunk and identify its main topic/section.

**Text Chunk:**
{chunk_text}

**Task:**
Identify:
1. The main section/topic this chunk belongs to
2. Content type (definition, tutorial, example, best_practice, troubleshooting)

**Response Format (JSON only):**
{{
    "section": "Customer Segmentation",
    "content_type": "best_practice"
}}

Respond ONLY with valid JSON:"""
    )

    chain = section_prompt | llm | StrOutputParser()

    try:
        # Only analyze first 500 chars to save tokens
        result = chain.invoke({"chunk_text": chunk_text[:500]})
        return json.loads(result.strip())
    except Exception as e:
        logging.warning(f"[Section Metadata] Failed: {e}")
        return {
            "section": "General",
            "content_type": "general"
        }


def enrich_chunk_metadata(
    chunk,
    doc_metadata: Dict[str, str],
    chunk_index: int,
    total_chunks: int,
    use_section_analysis: bool = True,
    llm = None
) -> None:
    """
    Enrich a chunk with intelligent metadata.

    Args:
        chunk: Document chunk to enrich
        doc_metadata: Document-level metadata from LLM
        chunk_index: Position of chunk
        total_chunks: Total number of chunks
        use_section_analysis: Whether to use LLM for section analysis
        llm: Language model (required if use_section_analysis=True)
    """
    # Add document-level metadata
    chunk.metadata.update(doc_metadata)

    # Add chunk-specific metadata
    chunk.metadata['chunk_index'] = chunk_index
    chunk.metadata['total_chunks'] = total_chunks

    # Optional: Analyze chunk content for section
    if use_section_analysis and llm and chunk_index % 3 == 0:
        # Only analyze every 3rd chunk to save API calls
        section_meta = extract_section_metadata(chunk.page_content, llm)
        chunk.metadata.update(section_meta)
    else:
        # Default section metadata
        chunk.metadata['section'] = "General"
        chunk.metadata['content_type'] = "general"
