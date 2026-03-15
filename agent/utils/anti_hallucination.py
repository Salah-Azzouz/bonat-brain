"""
Anti-Hallucination Safety Module

This module provides critical safeguards to prevent LLMs from generating
fake business data, which can have serious consequences for merchant decisions.
"""

import logging
import re
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


# Known hallucination patterns - update this list as you discover new patterns
HALLUCINATION_INDICATORS = {
    # Common fake numbers
    "numbers": [
        "150,000", "150000",  # Common fake revenue
        "500",  # Common fake average (when alone)
        "300",  # Common fake count (when alone)
        "1,000", "1000",  # Round numbers
        "10,000", "10000",
    ],

    # Warning phrases that indicate fake data
    "phrases": [
        "example", "sample", "placeholder", "illustration",
        "for instance", "typically", "generally",
        "approximate", "estimated", "roughly",
        "let's say", "suppose", "imagine",
        "hypothetical", "fictional"
    ],

    # Error indicators - these indicate the system failed to get data
    # NOTE: "not available" was removed because LLMs legitimately say this when
    # a specific metric doesn't exist (e.g., "loyalty data not available")
    "errors": [
        "encountered an issue", "couldn't generate", "couldn't determine",
        "unable to retrieve", "failed to fetch", "failed to retrieve",
        "no data found", "empty result", "query failed"
    ]
}


def detect_hallucination(text: str, context: str = "general") -> Tuple[bool, str]:
    """
    Detects if text contains hallucinated/fake business data.

    Args:
        text: The text to check for hallucination
        context: Context for detection ("insights", "data_response", "general")

    Returns:
        Tuple of (is_hallucinated: bool, reason: str)
    """
    text_lower = text.lower()

    # Check 1: Error message detection
    for error_phrase in HALLUCINATION_INDICATORS["errors"]:
        if error_phrase in text_lower:
            logger.warning(f"Detected error message in output: '{error_phrase}'")
            return True, f"Contains error message: '{error_phrase}'"

    # Check 2: Warning phrase detection
    for phrase in HALLUCINATION_INDICATORS["phrases"]:
        if phrase in text_lower:
            logger.warning(f"Detected hallucination phrase: '{phrase}'")
            return True, f"Contains hallucination indicator: '{phrase}'"

    # Check 3: Suspicious number patterns (only for data/insights context)
    if context in ["insights", "data_response"]:
        # Check for common fake numbers paired with currency
        if "SAR" in text or "ريال" in text:
            for fake_num in HALLUCINATION_INDICATORS["numbers"]:
                # Use regex to match the number as a standalone value
                pattern = r'\b' + re.escape(fake_num.replace(',', '')) + r'\b'
                if re.search(pattern, text.replace(',', '')):
                    logger.error(f"⚠️ CRITICAL: Detected fake number pattern: {fake_num} with currency indicator")
                    return True, f"Contains suspicious fake number: {fake_num}"

    return False, ""


def sanitize_response(text: str, context: str = "general") -> str:
    """
    Sanitizes a response by detecting and removing hallucinated content.

    Args:
        text: The response to sanitize
        context: Context for sanitization

    Returns:
        Sanitized text, or error message if hallucination detected
    """
    is_hallucinated, reason = detect_hallucination(text, context)

    if is_hallucinated:
        logger.error(f"⚠️ HALLUCINATION BLOCKED: {reason}")
        logger.error(f"Original text (first 200 chars): {text[:200]}")

        # Return safe error message based on context
        if context == "insights":
            return "I wasn't able to retrieve valid business metrics at this time. Please ask me specific questions about your data."
        elif context == "data_response":
            return "The data query returned invalid results. Please try rephrasing your question."
        else:
            return "I encountered an issue generating a valid response. Please try again."

    return text


def validate_data_response(response: str, query_result: Dict) -> Tuple[bool, str]:
    """
    Validates that a formatted response only uses data from the actual query result.

    Args:
        response: The formatted response text
        query_result: The actual data returned from database query

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    # Check 1: Basic hallucination detection
    is_hallucinated, reason = detect_hallucination(response, "data_response")
    if is_hallucinated:
        return False, f"Response contains hallucinated content: {reason}"

    # Check 2: If query returned no data, response shouldn't have numbers
    if not query_result or query_result.get("row_count", 0) == 0:
        # Look for any numbers in the response (except dates)
        numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', response)
        # Filter out years/dates (4-digit numbers starting with 20)
        data_numbers = [n for n in numbers if not (len(n) == 4 and n.startswith('20'))]

        if data_numbers:
            logger.error(f"⚠️ CRITICAL: Response contains numbers but query returned no data: {data_numbers}")
            return False, "Response contains fabricated numbers (query returned no data)"

    return True, ""


# Export all functions
__all__ = [
    "detect_hallucination",
    "sanitize_response",
    "validate_data_response",
    "HALLUCINATION_INDICATORS"
]
