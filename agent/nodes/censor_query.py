import logging
import re
from .types import State

def censor_query(state: State) -> dict:
    """Performs a security check to ensure the query only accesses the correct merchant's data."""
    logging.info("--- Censoring Query for Security ---")
    
    query = state.get("generated_query")
    merchant_id = str(state.get("merchant_id"))
    
    if not query or not merchant_id:
        return {"error_message": "Missing query or merchant_id for security check."}

    try:
        # Clean the query first (remove markdown if present)
        clean_query = query
        sql_match = re.search(r"```sql\n(.*?)\n```", query, re.DOTALL)
        if sql_match:
            clean_query = sql_match.group(1).strip()
        else:
            clean_query = query.replace("```sql", "").replace("```", "").strip()

        # Security Check: Use a robust regex to ensure the WHERE clause is correct
        # This looks for `idMerchant` (case-insensitive) followed by an equals sign and the correct merchant ID.
        # It allows for optional backticks and whitespace.
        pattern = re.compile(r"`?idMerchant`?\s*=\s*" + re.escape(merchant_id), re.IGNORECASE)
        
        if not pattern.search(clean_query):
            error_msg = (
                "Access Denied. All data queries must be restricted to your merchant account. "
                f"The query did not correctly filter for merchant ID {merchant_id}."
            )
            logging.warning(f"Query failed security check. Expected filter for merchant {merchant_id} not found in: '{clean_query}'")
            return {"error_message": error_msg}

        logging.info("Query passed security censorship.")
        return {}
        
    except Exception as e:
        logging.error(f"An unexpected error occurred during query censorship: {e}")
        return {"error_message": "A system error occurred while validating the query's security."}