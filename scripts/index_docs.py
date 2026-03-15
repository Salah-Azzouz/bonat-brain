"""
Index Bonat Documentation into Qdrant Vector Database

This script loads PDF documents from the docs folder and indexes them
into Qdrant for the agentic RAG system.

Usage:
    python scripts/index_docs.py
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from langchain_community.document_loaders import PyPDFLoader
from langchain_qdrant import QdrantVectorStore
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from intelligent_metadata import generate_metadata_with_llm, enrich_chunk_metadata

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def index_bonat_docs():
    """
    Index all PDF documents from the docs folder into Qdrant.
    """
    # Configuration
    DOCS_FOLDER = "docs"
    COLLECTION_NAME = "bonat_strategy"
    QDRANT_HOST = os.getenv("QDRANT_HOST", "51.44.2.49")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", "443"))
    QDRANT_API_KEY = os.getenv("QDRANT__SERVICE__API_KEY", "")

    logging.info(f"Starting indexing process...")
    logging.info(f"Docs folder: {DOCS_FOLDER}")
    logging.info(f"Collection: {COLLECTION_NAME}")
    logging.info(f"Qdrant Host: {QDRANT_HOST}")
    logging.info(f"Qdrant Port: {QDRANT_PORT}")
    logging.info(f"API Key configured: {'Yes' if QDRANT_API_KEY else 'No'}")

    # Initialize embeddings
    logging.info("Loading embedding model...")
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-large"
    )

    # Initialize LLM for intelligent metadata generation
    logging.info("Initializing LLM for intelligent metadata generation...")
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # Find all PDF files
    pdf_files = []
    if os.path.exists(DOCS_FOLDER):
        for file in os.listdir(DOCS_FOLDER):
            if file.endswith('.pdf'):
                pdf_files.append(os.path.join(DOCS_FOLDER, file))

    if not pdf_files:
        logging.error(f"No PDF files found in {DOCS_FOLDER}")
        return

    logging.info(f"Found {len(pdf_files)} PDF file(s): {[os.path.basename(f) for f in pdf_files]}")

    # Initialize text splitter - split by paragraphs
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ". ", " ", ""],  # Split by paragraph first
        length_function=len,
    )

    # Load and split documents
    all_documents = []

    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)
        logging.info(f"Loading: {filename}...")

        try:
            # Load PDF
            loader = PyPDFLoader(pdf_path)
            documents = loader.load()

            # Generate intelligent metadata using LLM
            sample_content = documents[0].page_content if documents else ""

            logging.info(f"  Analyzing content with LLM...")
            doc_metadata = generate_metadata_with_llm(filename, sample_content, llm)
            logging.info(f"  Category: {doc_metadata.get('doc_category')}, Type: {doc_metadata.get('doc_type')}")
            logging.info(f"  Topics: {doc_metadata.get('primary_topics')}")

            # Add metadata before chunking
            for doc in documents:
                doc.metadata['source_file'] = filename
                doc.metadata.update(doc_metadata)

            # Split into chunks by paragraph
            chunks = text_splitter.split_documents(documents)

            # Enrich each chunk with metadata
            for i, chunk in enumerate(chunks):
                enrich_chunk_metadata(
                    chunk,
                    doc_metadata,
                    chunk_index=i,
                    total_chunks=len(chunks),
                    use_section_analysis=False,  # Set to True for per-chunk analysis (slower)
                    llm=llm
                )

            all_documents.extend(chunks)

            logging.info(f"  Loaded {len(documents)} pages, created {len(chunks)} chunks")
            if chunks:
                logging.info(f"  Sample metadata: {dict(list(chunks[0].metadata.items())[:6])}")

        except Exception as e:
            logging.error(f"  Error loading {pdf_path}: {e}")

    if not all_documents:
        logging.error("No documents loaded. Exiting.")
        return

    logging.info(f"\nTotal chunks to index: {len(all_documents)}")

    # Create vector store
    logging.info("Creating vector store and indexing documents...")
    try:
        vectorstore = QdrantVectorStore.from_documents(
            all_documents,
            embedding=embeddings,
            url=f"https://{QDRANT_HOST}:{QDRANT_PORT}",
            api_key=QDRANT_API_KEY,
            collection_name=COLLECTION_NAME,
            force_recreate=True,
            prefer_grpc=False,
            verify=False,  # Disable SSL verification
        )

        logging.info(f"✅ Successfully indexed {len(all_documents)} chunks into '{COLLECTION_NAME}'")
        logging.info(f"✅ Vector database ready at {QDRANT_HOST}:{QDRANT_PORT}")

    except Exception as e:
        logging.error(f"Error creating vector store: {e}")
        raise


if __name__ == "__main__":
    index_bonat_docs()
