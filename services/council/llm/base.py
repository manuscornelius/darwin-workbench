"""LLMProvider — abstract interface every provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal


@dataclass
class LLMRequest:
    """A single LLM call as the council's agents see it."""

    messages: list[dict[str, Any]]
    system: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4000
    temperature: float | None = None
    # Provenance — stamped onto every event for audit purposes
    agent: str = "unspecified"
    prompt_version: str = "unversioned"


@dataclass
class LLMStreamEvent:
    """A single event emitted by the stream.

    Types:
      - text:           {"text": str}
      - tool_use_start: {"id": str, "name": str}
      - tool_use_input: {"id": str, "partial_json": str}
      - tool_use_end:   {"id": str, "input": dict}
      - turn_end:       {"stop_reason": str, "usage": {prompt, completion, cache_*}}
    """

    type: Literal["text", "tool_use_start", "tool_use_input", "tool_use_end", "turn_end"]
    data: dict[str, Any]
    # Provenance copied from the request
    agent: str = "unspecified"
    prompt_version: str = "unversioned"
    provider: str = "unspecified"
    model: str = ""


class LLMProvider(ABC):
    """Abstract LLM provider. Concrete classes wrap a specific API."""

    name: str = "unspecified"

    @abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        """Stream events for one LLM turn."""
        raise NotImplementedError
        yield  # pragma: no cover — make this an async generator for type checkers
