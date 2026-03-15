import os
import mysql.connector
from mysql.connector import pooling
from contextvars import ContextVar
from typing import List, Optional
from pymongo import MongoClient
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import BaseCallbackHandler
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT VARIABLES FOR REQUEST-SCOPED CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════
# This allows cost tracking callbacks to be automatically included in all LLM calls
# across the entire request lifecycle (main agent + all pipeline nodes)

_current_callbacks: ContextVar[List[BaseCallbackHandler]] = ContextVar('current_callbacks', default=[])


def set_callbacks(callbacks: List[BaseCallbackHandler]) -> None:
    """Set callbacks for the current request context."""
    _current_callbacks.set(callbacks)


def get_callbacks() -> List[BaseCallbackHandler]:
    """Get callbacks for the current request context."""
    return _current_callbacks.get()


def clear_callbacks() -> None:
    """Clear callbacks after request completes."""
    _current_callbacks.set([])

load_dotenv()
logging.info("Environment variables loaded.")

# Core Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-please-change-in-production")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 480))  # 8 hours default
MAX_HISTORY_TURNS = 5

# Merchant Configuration
# Hardcoded merchant IDs - to add more merchants, add them to this list
ALLOWED_MERCHANTS = ["1032"]
DEFAULT_MERCHANT = "1032"
logging.info(f"Merchant config loaded: allowed={ALLOWED_MERCHANTS}, default={DEFAULT_MERCHANT}")

import zoneinfo
MERCHANT_TIMEZONE = zoneinfo.ZoneInfo("Asia/Riyadh")

def get_merchant_now():
    """Current datetime in merchant timezone. Use for all user-facing date computations."""
    from datetime import datetime
    return datetime.now(tz=MERCHANT_TIMEZONE)

# LLM Configuration
# gpt-4.1-mini: Best balance of speed (4-16s), structured output compliance,
# and cost for our simple tool-calling pattern (classify → call → format).
LLM_MODEL_NAME = os.getenv("LLM_MODEL", "gpt-4.1-mini")
_base_llm = ChatOpenAI(
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0,
    model=LLM_MODEL_NAME,
    seed=42,  # Improves reproducibility with temperature=0 (OpenAI docs)
    stream_usage=True,  # Enable token usage tracking for streaming responses
)
logging.info(f"LLM configured with model: {LLM_MODEL_NAME}")


def get_llm() -> ChatOpenAI:
    """
    Get LLM instance with current request's callbacks attached.

    This should be used instead of `_base_llm` to ensure cost tracking
    works across all pipeline nodes.

    Usage:
        from agent.config import get_llm
        llm = get_llm()
        chain = prompt | llm | StrOutputParser()
    """
    callbacks = get_callbacks()
    if callbacks:
        return _base_llm.with_config(callbacks=callbacks)
    return _base_llm


# Database Configuration - Use individual environment variables
# Query timeout set to 30 seconds to prevent long-running queries from hanging
QUERY_TIMEOUT_SECONDS = 30

DB_CONFIG = {
    'host': os.getenv("DB_HOST"),
    'database': os.getenv("DB_DATABASE"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'port': int(os.getenv("DB_PORT")),
    'connection_timeout': 10,  # Connection timeout in seconds
}
logging.info(f"MySQL DB configured for host: {DB_CONFIG['host']}:{DB_CONFIG['port']}, user: {DB_CONFIG['user']}, database: {DB_CONFIG['database']}")

# MongoDB Configuration - Use individual environment variables
MONGO_CONFIG = {
    'host': os.getenv("MONGO_HOST"),
    'port': int(os.getenv("MONGO_PORT")),
    'username': os.getenv("MONGO_USER"),
    'password': os.getenv("MONGO_PASSWORD"),
    'tls': os.getenv("MONGO_TLS", "true").lower() == "true",  # Default to TLS enabled for production
}
MONGO_DATABASE_NAME = os.getenv("MONGO_DATABASE")
logging.info(f"MongoDB configured for host: {MONGO_CONFIG['host']}:{MONGO_CONFIG['port']}, user: {MONGO_CONFIG['username']}, database: {MONGO_DATABASE_NAME}")

# Database Connection Pool
# Reuses TCP+TLS connections instead of creating a new one per query.
# PooledMySQLConnection.close() returns the connection to the pool (not a real close).
_db_pool = None
try:
    _db_pool = pooling.MySQLConnectionPool(
        pool_name="bonat_pool",
        pool_size=5,
        pool_reset_session=False,  # Our code sets session vars per query already
        **DB_CONFIG,
    )
    logging.info("MySQL connection pool created (size=5)")
except Exception as e:
    logging.warning(f"MySQL connection pool creation failed: {e}. Falling back to per-request connections.")


def get_db_connection():
    """Get a MySQL connection from the pool (or create a new one as fallback)."""
    if _db_pool:
        try:
            return _db_pool.get_connection()
        except Exception as e:
            logging.warning(f"Pool connection failed: {e}. Creating direct connection.")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logging.error(f"Error connecting to MySQL: {e}")
        return None

def get_table_schemas():
    """Inspects the MySQL database and retrieves all table schemas."""
    schemas = {}
    conn = None
    try:
        logging.info("Attempting to connect to MySQL and load schemas...")
        conn = get_db_connection()
        if not conn:
            raise ConnectionError("Failed to get database connection.")

        logging.info("MySQL connection established. Fetching tables...")
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES;")
        all_table_names = [row[0] for row in cursor.fetchall()]
        logging.info(f"Found {len(all_table_names)} tables in database.")

        for table_name in all_table_names:
            # The result for SHOW CREATE TABLE is a tuple: (table_name, create_table_statement)
            cursor.execute(f"SHOW CREATE TABLE `{table_name}`;")
            create_statement = cursor.fetchone()[1]
            schemas[table_name] = create_statement
            logging.info(f"Loaded schema for table: {table_name}")

        if not schemas:
            logging.warning("No table schemas were loaded. The database might be empty.")

        logging.info(f"Dynamically discovered {len(schemas)} tables in MySQL.")
        return schemas
    except Exception as e:
        logging.error(f"Error getting table schemas: {e}", exc_info=True)
        return {}
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def reload_schemas():
    """Force reload of schemas - useful if initial load failed."""
    global mysql_schemas
    logging.info("Reloading MySQL schemas...")
    mysql_schemas = get_table_schemas()
    return mysql_schemas

# Load schemas on startup - with error handling
try:
    mysql_schemas = get_table_schemas()
    if not mysql_schemas:
        logging.error("CRITICAL: No MySQL schemas loaded! Database queries will fail.")
    else:
        logging.info(f"Successfully loaded {len(mysql_schemas)} MySQL table schemas.")
except Exception as e:
    logging.error(f"CRITICAL ERROR loading MySQL schemas: {e}")
    mysql_schemas = {}

def get_mongodb_client():
    """Get MongoDB client connection."""
    try:
        # Try connecting with authentication first
        if MONGO_CONFIG['username'] and MONGO_CONFIG['password']:
            client = MongoClient(
                host=MONGO_CONFIG['host'],
                port=MONGO_CONFIG['port'],
                username=MONGO_CONFIG['username'],
                password=MONGO_CONFIG['password'],
                authSource='admin',
                tls=MONGO_CONFIG['tls'],
                tlsAllowInvalidCertificates=True,
                directConnection=True,
                retryWrites=False
            )
        else:
            # Fallback to no authentication for local development
            client = MongoClient(
                host=MONGO_CONFIG['host'],
                port=MONGO_CONFIG['port'],
                retryWrites=False
            )

        client.admin.command('ping')
        return client
    except Exception as e:
        logging.error(f"MongoDB connection error: {e}")
        return None

_mongodb_collections = None

def _init_mongodb():
    """Initialize MongoDB collections and create indexes (called once)."""
    client = get_mongodb_client()
    if client:
        logging.info(f"Accessing MongoDB database: {MONGO_DATABASE_NAME}")
        db = client[MONGO_DATABASE_NAME]

        # Initialize collections with indexes
        logging.info("Initializing 'users' collection and indexes...")
        db.users.create_index("email", unique=True)
        db.users.create_index("user_id", unique=True)

        logging.info("Initializing 'conversations' collection and indexes...")
        db.conversations.create_index("conversation_id", unique=True)
        db.conversations.create_index("user_id")

        logging.info("Initializing 'history' collection and indexes...")
        db.history.create_index("conversation_id")
        db.history.create_index("user_id")
        db.history.create_index("merchant_id")
        db.history.create_index("timestamp")
        # Compound index for efficient history queries by user + merchant
        db.history.create_index([("user_id", 1), ("merchant_id", 1), ("timestamp", -1)])
        logging.info("MongoDB collections initialized successfully.")

        return {
            'users': db.users,
            'conversations': db.conversations,
            'history': db.history
        }
    return None

def get_mongodb_collections():
    """Get all required MongoDB collections (lazy singleton)."""
    global _mongodb_collections
    if _mongodb_collections is None:
        _mongodb_collections = _init_mongodb()
    return _mongodb_collections