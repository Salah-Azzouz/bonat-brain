import logging
from agent.config import get_db_connection
from .types import State

def validate_request(state: State) -> dict:
    """
    Validates if data is available for the merchant.
    The schema compatibility check is removed to allow the LLM more freedom in query generation.
    """
    logging.info("--- Validating Data Availability ---")
    
    question = state["confirmed_meaning"]
    table_name = state.get("selected_table")
    merchant_id = state.get("merchant_id")

    if not merchant_id or not table_name:
        # If we're missing key info, just proceed and let the query handle it.
        return {"validation_result": "YES"}

    conn = get_db_connection()
    if not conn:
        logging.error("Database connection failed during validation.")
        return {"validation_result": "YES"}  # Continue anyway

    try:
        cursor = conn.cursor()

        # Simple check: Does any data exist for this merchant in the selected table?
        # This prevents running complex queries on empty tables.
        check_query = f'SELECT 1 FROM `{table_name}` WHERE `idMerchant` = %s LIMIT 1'
        merchant_id_int = int(merchant_id)

        logging.info(f"Validating data for merchant {merchant_id_int} in table {table_name}")
        logging.info(f"Validation query: {check_query} with merchant_id={merchant_id_int}")

        cursor.execute(check_query, (merchant_id_int,))
        result = cursor.fetchone()

        logging.info(f"Validation result: {result}")

        if not result:
            # No data exists for this merchant in the selected table — this is a normal business state.
            logging.info(f"No data for merchant {merchant_id} in table {table_name}. Merchant simply has no {table_name} data.")

            # Map table names to human-friendly descriptions
            table_descriptions = {
                "PickupOrderSummary": "pickup orders",
                "CampaignSummary": "campaigns",
                "GeographicPerformanceSummary": "branch performance data",
                "PaymentAnalyticsSummary": "payment analytics",
                "LoyaltyProgramSummary": "loyalty program data",
                "CustomerSummary": "customer data",
                "DailyPerformanceSummary": "daily performance data",
                "MonthlyPerformanceSummary": "monthly performance data",
                "MerchantSummary": "merchant summary data",
                "POSComparisonSummary": "POS comparison data",
            }
            friendly_name = table_descriptions.get(table_name, table_name)

            message = (
                f"You currently don't have any {friendly_name}. "
                f"This is normal — it simply means your account hasn't generated this type of data yet."
            )
            return {
                "validation_result": "NO",
                "data_availability_message": message
            }
        
        logging.info(f"Data availability confirmed for merchant {merchant_id} in {table_name}.")
        return {"validation_result": "YES"}
            
    except Exception as e:
        logging.error(f"Error checking data availability: {e}")
        # Let the query execution handle the error, but log it here.
        return {"validation_result": "YES"}
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()