from typing import TypedDict, List, Any, Optional

class State(TypedDict):
    user_prompt: str
    merchant_id: str
    conversation_history: List[dict]
    history: list

    # Data analysis fields
    confirmed_meaning: str
    selected_table: str
    table_schema: str
    validation_result: str
    data_availability_message: str
    generated_query: str
    execution_result: Any
    error_message: str
    retry_count: int
    analysis_insight: str

    # Date context (set by data_pipeline, read by create_query)
    current_date: Optional[str]
    current_day_name: Optional[str]

    # Structured routing (set by main agent's tool call)
    intent_category: Optional[str]

    # Query consistency fields (for follow-up questions)
    previous_query_columns: Optional[str]  # Columns used in last successful query
    previous_query_metric: Optional[str]   # The metric type (e.g., "unique_customers", "daily_visits")

    # Self-correction fallback (set by select_table when top-2 candidates differ)
    fallback_table: Optional[str]
    fallback_schema: Optional[str]

    # Query source tracking
    query_source: Optional[str]          # "structured", "legacy"