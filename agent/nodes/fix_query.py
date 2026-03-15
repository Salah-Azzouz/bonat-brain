import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from agent.config import get_llm
from .types import State

def fix_query(state: State) -> dict:
    """Analyzes a failed SQL query and attempts to fix it."""
    logging.info("--- Fixing SQL Query ---")
    
    original_query = state["generated_query"]
    error_message = state["error_message"]
    table_schema = state["table_schema"]
    
    prompt = ChatPromptTemplate.from_template(
        """Fix this failed MySQL query. Return ONLY the corrected SQL.

**Schema:**
```sql
{table_schema}
```

**Failed Query:**
```sql
{original_query}
```

**Error:** {error_message}

**Rules:** Use only the table above. Enclose identifiers in backticks. If table is missing, return: `SELECT 'Table not available' AS error`

**Corrected SQL:**"""
    )
    
    chain = prompt | get_llm() | StrOutputParser()
    fixed_query = chain.invoke({
        "original_query": original_query,
        "error_message": error_message,
        "table_schema": table_schema
    })
    
    logging.info(f"Generated fixed query: {fixed_query}")
    return {
        "generated_query": fixed_query,
        "retry_count": state.get("retry_count", 0) + 1
    }