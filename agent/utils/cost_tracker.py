"""
Cost Tracking Callback for LangChain

This module provides automatic cost tracking for all LLM calls made through LangChain.
It captures token usage, calculates costs, and provides aggregated metrics per request.

For streaming calls where OpenAI doesn't return token counts, we use tiktoken to estimate.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from threading import Lock
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

# Import tiktoken for token counting when OpenAI doesn't provide it
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logging.warning("tiktoken not available - token estimation will be disabled")

logger = logging.getLogger(__name__)


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """
    Count tokens in text using tiktoken.
    Falls back to word-based estimation if tiktoken unavailable.
    """
    if not text:
        return 0

    if TIKTOKEN_AVAILABLE:
        try:
            # Get encoding for the model (falls back to cl100k_base for newer models)
            try:
                encoding = tiktoken.encoding_for_model(model)
            except KeyError:
                encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception as e:
            logger.warning(f"tiktoken encoding failed: {e}")

    # Fallback: rough estimate (1 token ≈ 4 characters for English)
    return len(text) // 4


# ═══════════════════════════════════════════════════════════════════════════════
# PRICING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
# Prices per 1M tokens (as of December 2024)
# Update these when OpenAI changes pricing

MODEL_PRICING = {
    # GPT-4o Mini
    "gpt-4o-mini": {
        "input": 0.15,   # $0.15 per 1M input tokens
        "output": 0.60,  # $0.60 per 1M output tokens
    },
    "gpt-4o-mini-2024-07-18": {
        "input": 0.15,
        "output": 0.60,
    },

    # GPT-4o
    "gpt-4o": {
        "input": 2.50,   # $2.50 per 1M input tokens
        "output": 10.00, # $10.00 per 1M output tokens
    },
    "gpt-4o-2024-08-06": {
        "input": 2.50,
        "output": 10.00,
    },

    # GPT-4 Turbo
    "gpt-4-turbo": {
        "input": 10.00,
        "output": 30.00,
    },
    "gpt-4-turbo-preview": {
        "input": 10.00,
        "output": 30.00,
    },

    # GPT-3.5 Turbo
    "gpt-3.5-turbo": {
        "input": 0.50,
        "output": 1.50,
    },

    # Embeddings
    "text-embedding-3-large": {
        "input": 0.13,
        "output": 0.0,  # Embeddings don't have output tokens
    },
    "text-embedding-3-small": {
        "input": 0.02,
        "output": 0.0,
    },
}

# Default pricing for unknown models
DEFAULT_PRICING = {
    "input": 1.00,   # Conservative estimate
    "output": 3.00,
}


def get_model_pricing(model_name: str) -> Dict[str, float]:
    """
    Get pricing for a model by name.
    Falls back to default pricing if model not found.
    """
    # Normalize model name (lowercase, strip version suffixes for matching)
    model_lower = model_name.lower()

    # Try exact match first
    if model_lower in MODEL_PRICING:
        return MODEL_PRICING[model_lower]

    # Try prefix match (e.g., "gpt-4o-mini-2024" matches "gpt-4o-mini")
    for known_model, pricing in MODEL_PRICING.items():
        if model_lower.startswith(known_model):
            return pricing

    logger.warning(f"Unknown model '{model_name}', using default pricing")
    return DEFAULT_PRICING


def calculate_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int
) -> Dict[str, float]:
    """
    Calculate cost for a single LLM call.

    Returns:
        Dict with input_cost, output_cost, and total_cost in USD
    """
    pricing = get_model_pricing(model_name)

    # Convert from per-1M tokens to per-token
    input_rate = pricing["input"] / 1_000_000
    output_rate = pricing["output"] / 1_000_000

    input_cost = input_tokens * input_rate
    output_cost = output_tokens * output_rate
    total_cost = input_cost + output_cost

    return {
        "input_cost": round(input_cost, 8),
        "output_cost": round(output_cost, 8),
        "total_cost": round(total_cost, 8),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# COST TRACKING CALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

class CostTrackingCallback(BaseCallbackHandler):
    """
    LangChain callback handler that tracks token usage and costs.

    Usage:
        callback = CostTrackingCallback()
        llm = ChatOpenAI(..., callbacks=[callback])

        # After agent execution
        cost_data = callback.get_cost_summary()
    """

    def __init__(self):
        """Initialize the cost tracker."""
        super().__init__()
        self._lock = Lock()
        self._reset()

    def _reset(self):
        """Reset all tracking data."""
        self._llm_calls: List[Dict[str, Any]] = []
        self._tools_used: List[str] = []
        self._start_time: Optional[float] = None
        self._current_call_start: Optional[float] = None
        self._current_model: Optional[str] = None
        self._current_prompts: List[str] = []  # Store prompts for token estimation

    # ═══════════════════════════════════════════════════════════════════════════
    # LLM Callbacks
    # ═══════════════════════════════════════════════════════════════════════════

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM starts processing."""
        with self._lock:
            if self._start_time is None:
                self._start_time = time.time()

            self._current_call_start = time.time()

            # Try to extract model name
            self._current_model = None
            if serialized:
                # Try different paths where model name might be stored
                self._current_model = serialized.get("kwargs", {}).get("model_name")
                if not self._current_model:
                    self._current_model = serialized.get("kwargs", {}).get("model")
                if not self._current_model:
                    self._current_model = serialized.get("name", "unknown")

            # Store prompts for token estimation if OpenAI doesn't return usage
            self._current_prompts = prompts if prompts else []

            logger.debug(f"[CostTracker] on_llm_start - model: {self._current_model}, prompts: {len(self._current_prompts)}")

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM finishes processing."""
        with self._lock:
            # Calculate latency
            latency_ms = 0
            if self._current_call_start:
                latency_ms = int((time.time() - self._current_call_start) * 1000)

            # Extract token usage from response
            llm_output = response.llm_output or {}
            token_usage = llm_output.get("token_usage", {})

            logger.debug(f"[CostTracker] on_llm_end - llm_output: {llm_output}")

            # Try alternative key names for token usage
            if not token_usage:
                token_usage = llm_output.get("usage", {})

            # Try alternative locations for token usage (streaming may put it elsewhere)
            if not token_usage and response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, 'generation_info') and gen.generation_info:
                            gen_info = gen.generation_info
                            token_usage = gen_info.get("token_usage", {}) or gen_info.get("usage", {})
                            if token_usage:
                                logger.debug(f"[CostTracker] Found token_usage in generation_info: {token_usage}")
                                break
                    if token_usage:
                        break

            logger.debug(f"[CostTracker] on_llm_end - final token_usage: {token_usage}")

            # Handle different token usage formats
            input_tokens = (
                token_usage.get("prompt_tokens") or
                token_usage.get("input_tokens") or
                0
            )
            output_tokens = (
                token_usage.get("completion_tokens") or
                token_usage.get("output_tokens") or
                0
            )

            # If no token usage from OpenAI (streaming mode), estimate with tiktoken
            model_name = llm_output.get("model_name") or self._current_model or "gpt-4o-mini"
            estimated = False

            if input_tokens == 0 and self._current_prompts:
                # Estimate input tokens from stored prompts
                input_tokens = sum(count_tokens(p, model_name) for p in self._current_prompts)
                estimated = True
                logger.debug(f"[CostTracker] Estimated input tokens: {input_tokens}")

            if output_tokens == 0 and response.generations:
                # Estimate output tokens from response content
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, 'text') and gen.text:
                            output_tokens += count_tokens(gen.text, model_name)
                        elif hasattr(gen, 'message') and hasattr(gen.message, 'content'):
                            output_tokens += count_tokens(gen.message.content, model_name)
                if output_tokens > 0:
                    estimated = True
                    logger.debug(f"[CostTracker] Estimated output tokens: {output_tokens}")

            if estimated:
                logger.debug(f"[CostTracker] Token counts estimated via tiktoken: in={input_tokens}, out={output_tokens}")

            total_tokens = token_usage.get("total_tokens") or (input_tokens + output_tokens)

            # Get model name from response or use cached value
            model_name = llm_output.get("model_name") or self._current_model or "unknown"

            # Calculate cost
            cost = calculate_cost(model_name, input_tokens, output_tokens)

            # Store the call data
            call_data = {
                "model": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "input_cost": cost["input_cost"],
                "output_cost": cost["output_cost"],
                "total_cost": cost["total_cost"],
                "latency_ms": latency_ms,
                "success": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self._llm_calls.append(call_data)

            logger.debug(
                f"[CostTracker] LLM call: model={model_name}, "
                f"tokens={input_tokens}+{output_tokens}={total_tokens}, "
                f"cost=${cost['total_cost']:.6f}, latency={latency_ms}ms"
            )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM encounters an error."""
        with self._lock:
            latency_ms = 0
            if self._current_call_start:
                latency_ms = int((time.time() - self._current_call_start) * 1000)

            # Still record the failed call (it may have consumed tokens)
            call_data = {
                "model": self._current_model or "unknown",
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "input_cost": 0.0,
                "output_cost": 0.0,
                "total_cost": 0.0,
                "latency_ms": latency_ms,
                "success": False,
                "error": str(error),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self._llm_calls.append(call_data)

            logger.warning(f"[CostTracker] LLM error: {error}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Tool Callbacks
    # ═══════════════════════════════════════════════════════════════════════════

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        inputs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool starts execution."""
        with self._lock:
            tool_name = serialized.get("name", "unknown")
            if tool_name not in self._tools_used:
                self._tools_used.append(tool_name)

    # ═══════════════════════════════════════════════════════════════════════════
    # Cost Summary Methods
    # ═══════════════════════════════════════════════════════════════════════════

    def get_cost_summary(self) -> Dict[str, Any]:
        """
        Get aggregated cost summary for all LLM calls tracked.

        Returns:
            Dict containing:
                - input_tokens: Total input tokens
                - output_tokens: Total output tokens
                - total_tokens: Total tokens
                - cost_usd: Total cost in USD
                - model: Primary model used
                - latency_ms: Total latency
                - llm_calls: Number of LLM calls
                - tools_used: List of tools that were invoked
                - calls_detail: List of individual call data (optional)
        """
        with self._lock:
            if not self._llm_calls:
                return {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "model": "none",
                    "latency_ms": 0,
                    "llm_calls": 0,
                    "tools_used": [],
                }

            # Aggregate totals
            total_input_tokens = sum(c["input_tokens"] for c in self._llm_calls)
            total_output_tokens = sum(c["output_tokens"] for c in self._llm_calls)
            total_tokens = sum(c["total_tokens"] for c in self._llm_calls)
            total_cost = sum(c["total_cost"] for c in self._llm_calls)
            total_latency = sum(c["latency_ms"] for c in self._llm_calls)

            # Get primary model (most used)
            models = [c["model"] for c in self._llm_calls if c["model"] != "unknown"]
            primary_model = max(set(models), key=models.count) if models else "unknown"

            return {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_tokens,
                "cost_usd": round(total_cost, 8),
                "model": primary_model,
                "latency_ms": total_latency,
                "llm_calls": len(self._llm_calls),
                "tools_used": self._tools_used.copy(),
            }

    def get_detailed_breakdown(self) -> List[Dict[str, Any]]:
        """
        Get detailed breakdown of each LLM call.

        Returns:
            List of individual call data dictionaries
        """
        with self._lock:
            return self._llm_calls.copy()

    def reset(self):
        """Reset the tracker for a new request."""
        with self._lock:
            self._reset()

    @property
    def total_cost(self) -> float:
        """Quick access to total cost in USD."""
        with self._lock:
            return sum(c["total_cost"] for c in self._llm_calls)

    @property
    def total_tokens(self) -> int:
        """Quick access to total tokens used."""
        with self._lock:
            return sum(c["total_tokens"] for c in self._llm_calls)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def create_cost_tracker() -> CostTrackingCallback:
    """
    Factory function to create a new cost tracker instance.

    Usage:
        callback = create_cost_tracker()
        agent = create_main_agent(merchant_id, callbacks=[callback])
        # ... after execution ...
        cost = callback.get_cost_summary()
    """
    return CostTrackingCallback()


# Export all public components
__all__ = [
    "CostTrackingCallback",
    "create_cost_tracker",
    "calculate_cost",
    "get_model_pricing",
    "MODEL_PRICING",
]
