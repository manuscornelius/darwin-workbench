"""
LLM provider errors.

Maps to the DW-005x error family from Section 22 (error taxonomy) so
troubleshooting runbooks (RB-02) can pattern-match from exception type
to runbook action.
"""
from __future__ import annotations


class LLMError(Exception):
    """Base for all LLM provider errors.

    Subclasses set error_code to a specific DW-005x value. Keep this
    hierarchy narrow - add new subclasses only when runbooks need to
    branch on them.
    """
    error_code: str = "DW-0050"


class LLMThrottleError(LLMError):
    """Provider rate-limited us. Retryable with backoff (RB-02)."""
    error_code = "DW-0051"


class LLMTimeoutError(LLMError):
    """Provider exceeded the per-call timeout. Retryable."""
    error_code = "DW-0052"


class LLMContextExceededError(LLMError):
    """Request exceeded the model context window. NOT retryable - caller
    must reduce context before resubmitting."""
    error_code = "DW-0053"


class LLMProviderError(LLMError):
    """Provider-specific error not covered by the categories above.

    Carries the provider original error message/code for the audit trail.
    """
    error_code = "DW-0054"
