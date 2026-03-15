import logging
import traceback
import re

from agent.config import get_db_connection, QUERY_TIMEOUT_SECONDS
from .types import State


def execute_query(state: State) -> dict:
    """Executes a SQL query against the database and returns the result."""
    logging.info("--- Executing SQL Query ---")
    query = state["generated_query"]
    table_name = state.get("selected_table", "")

    # Clean SQL from markdown
    clean_query = query
    sql_match = re.search(r"```sql\n(.*?)\n```", query, re.DOTALL)
    if sql_match:
        clean_query = sql_match.group(1).strip()
    else:
        clean_query = query.replace("```sql", "").replace("```", "").strip()

    # CRITICAL SAFETY FEATURE: Add a LIMIT to prevent excessively large results
    # that could crash the LLM context.
    if "limit" not in clean_query.lower():
        if clean_query.endswith(';'):
            clean_query = clean_query[:-1] + " LIMIT 100;"
        else:
            clean_query += " LIMIT 100"

    logging.info(f"Executing query: {clean_query}")

    conn = get_db_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {QUERY_TIMEOUT_SECONDS * 1000}")
        cursor.execute("SET time_zone = '+03:00'")  # Asia/Riyadh = UTC+3

        cursor.execute(clean_query)
        result = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]
        result_dicts = [dict(zip(column_names, row)) for row in result]

        state["execution_result"] = {
            "success": True,
            "data": result_dicts,
            "row_count": len(result),
            "columns": column_names
        }
        logging.info(f"Query executed successfully. Result rows: {len(result)}")
        return {"execution_result": {"success": True, "data": result_dicts, "row_count": len(result), "columns": column_names}}
    except Exception as e:
        error_message = str(e)

        if "max_execution_time" in error_message.lower() or "query execution was interrupted" in error_message.lower():
            logging.warning(f"Query timeout on table {table_name}: {clean_query[:200]}...")
            user_message = (
                f"The query took too long to execute (>{QUERY_TIMEOUT_SECONDS}s). "
                "Try asking for a smaller date range or a different summary table."
            )
            return {"execution_result": {"success": False, "error": user_message, "timeout": True}}

        full_error = f"Error executing query: {e}\n{traceback.format_exc()}"
        logging.error(full_error)
        return {"execution_result": {"success": False, "error": error_message}}
    finally:
        if conn:
            conn.close()
