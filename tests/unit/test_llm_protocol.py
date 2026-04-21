"""Tests proving the LLMProvider protocol shape and envelope models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestration.llm import (
    ExecutionTier,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    Message,
    Role,
    StopReason,
)


def _valid_request_kwargs() -> dict:
    return dict(
        model="claude-sonnet-4-5",
        system_prompt="You are the Darwin intake agent.",
        messages=[Message(role=Role.USER, content="Hello")],
        prompt_name="intake",
        prompt_version="1.0.0",
        agent_name="intake",
        operation_id="eng_abc123",
    )


def _valid_response_kwargs() -> dict:
    return dict(
        completion="Hello, I am the intake agent.",
        stop_reason=StopReason.END_TURN,
        prompt_tokens=100,
        completion_tokens=50,
        model="claude-sonnet-4-5",
        latency_ms=342,
        prompt_hash="a" * 64,
        completion_hash="b" * 64,
    )


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

def test_llm_request_minimal_construction() -> None:
    req = LLMRequest(**_valid_request_kwargs())
    assert req.max_tokens == 4096
    assert req.temperature == 0.1
    assert req.cache_eligible is False
    assert req.execution_tier == ExecutionTier.SONNET


def test_llm_request_requires_at_least_one_message() -> None:
    kwargs = _valid_request_kwargs()
    kwargs["messages"] = []
    with pytest.raises(ValidationError):
        LLMRequest(**kwargs)


def test_llm_request_temperature_bounds() -> None:
    kwargs = _valid_request_kwargs()
    kwargs["temperature"] = 1.5
    with pytest.raises(ValidationError):
        LLMRequest(**kwargs)


def test_llm_request_extra_forbid() -> None:
    kwargs = _valid_request_kwargs()
    kwargs["typo"] = "should fail"
    with pytest.raises(ValidationError):
        LLMRequest(**kwargs)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def test_llm_response_computed_properties() -> None:
    resp = LLMResponse(**_valid_response_kwargs())
    assert resp.total_tokens == 150
    assert resp.cache_hit is False


def test_llm_response_cache_hit_flag() -> None:
    kwargs = _valid_response_kwargs()
    kwargs["cache_read_tokens"] = 800
    resp = LLMResponse(**kwargs)
    assert resp.cache_hit is True


def test_llm_response_hash_length_validated() -> None:
    """prompt_hash and completion_hash must be 64 hex chars (SHA-256)."""
    kwargs = _valid_response_kwargs()
    kwargs["prompt_hash"] = "too_short"
    with pytest.raises(ValidationError):
        LLMResponse(**kwargs)


# ---------------------------------------------------------------------------
# Protocol conformance (runtime_checkable)
# ---------------------------------------------------------------------------

class _FakeProvider:
    """Test double implementing LLMProvider structurally."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(**_valid_response_kwargs())


class _MissingComplete:
    """Missing the complete() method - must NOT satisfy the protocol."""
    pass


def test_fake_provider_satisfies_protocol() -> None:
    """Structural typing: anything with the right shape counts as LLMProvider."""
    provider = _FakeProvider()
    assert isinstance(provider, LLMProvider)


def test_incomplete_provider_rejected() -> None:
    provider = _MissingComplete()
    assert not isinstance(provider, LLMProvider)


@pytest.mark.asyncio
async def test_fake_provider_end_to_end() -> None:
    """Send a request through the fake provider and verify the envelope."""
    provider: LLMProvider = _FakeProvider()
    request = LLMRequest(**_valid_request_kwargs())
    response = await provider.complete(request)
    assert response.total_tokens == 150
    assert response.stop_reason == StopReason.END_TURN
    assert len(response.prompt_hash) == 64
