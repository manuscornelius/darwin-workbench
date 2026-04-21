"""LLM Provider abstraction.

Public API:
  - LLMProvider: the protocol every backend implements
  - LLMRequest, LLMResponse, Message: the request/response envelope
  - ExecutionTier, Role, StopReason: enums
  - LLMError and subclasses: error taxonomy mapped to DW-005x (Section 22)
"""
from .errors import (
    LLMContextExceededError,
    LLMError,
    LLMProviderError,
    LLMThrottleError,
    LLMTimeoutError,
)
from .protocol import (
    ExecutionTier,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    Message,
    Role,
    StopReason,
)

__all__ = [
    "ExecutionTier",
    "LLMContextExceededError",
    "LLMError",
    "LLMProvider",
    "LLMProviderError",
    "LLMRequest",
    "LLMResponse",
    "LLMThrottleError",
    "LLMTimeoutError",
    "Message",
    "Role",
    "StopReason",
]
