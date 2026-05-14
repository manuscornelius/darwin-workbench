"""Provider lookup by name. Single source of truth for which provider is active."""

from __future__ import annotations

from llm.anthropic_direct import AnthropicDirectProvider
from llm.base import LLMProvider
from llm.bedrock import BedrockProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic_direct": AnthropicDirectProvider,
    "bedrock": BedrockProvider,
}

_INSTANCES: dict[str, LLMProvider] = {}


def get_provider(name: str = "anthropic_direct") -> LLMProvider:
    """Return a singleton provider instance by name."""
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown LLM provider: {name}. Available: {list(_PROVIDERS)}")
    if name not in _INSTANCES:
        _INSTANCES[name] = _PROVIDERS[name]()
    return _INSTANCES[name]
