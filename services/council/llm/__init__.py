"""LLM provider abstraction.

Agents call LLMProvider.stream() with a request. The concrete provider
(Anthropic direct, Bedrock, etc.) handles transport, streaming, and metadata
stamping. Swapping providers is a one-file change.
"""

from llm.base import LLMProvider, LLMRequest, LLMStreamEvent
from llm.registry import get_provider

__all__ = ["LLMProvider", "LLMRequest", "LLMStreamEvent", "get_provider"]
