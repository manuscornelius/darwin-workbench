"""
LLM Provider Protocol
=====================

The contract every LLM backend must satisfy. Two backends planned:

- AnthropicProvider: calls api.anthropic.com directly via the anthropic SDK.
  For local dev before AWS Bedrock is wired up.
- BedrockProvider: calls Bedrock via boto3. Production. Spec-required for
  Layer 2 VPC endpoint, approved model list enforcement, CloudWatch metric
  emission, prompt caching.

Both produce identical LLMResponse shapes so swapping is transparent. Agent
nodes code against this protocol - never against a specific SDK.

Spec references:
  - Section 02: BedrockClient wrapper: retry, token tracking, prompt version
    stamping, CloudWatch metric emission, prompt caching
  - Section 12: Prompt caching is mandatory
  - Section 21: LLM call telemetry (prompt_hash, completion_hash, versions,
    tokens, latency, guardrail_action, prompt_cache_hit)
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Role(str, Enum):
    """Chat message role."""
    USER = "user"
    ASSISTANT = "assistant"


class StopReason(str, Enum):
    """Why the LLM stopped generating.

    Values align with Anthropic API. Bedrock variants are mapped to these
    in BedrockProvider. Unknown reasons map to UNKNOWN rather than raising -
    telemetry must never fail the whole call.
    """
    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    TOOL_USE = "tool_use"
    UNKNOWN = "unknown"


class ExecutionTier(str, Enum):
    """Execution tier from the Request Classifier (Section 12).

    Drives which model the provider invokes. The classifier sets this on
    the request; the provider respects it.
    """
    SONNET = "sonnet"
    HAIKU = "haiku"


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class Message(BaseModel):
    """A chat message. Extensible to multipart later if we need it."""
    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class LLMRequest(BaseModel):
    """Everything needed to invoke an LLM and log the call for audit.

    The provider is responsible for:
      - Computing prompt_hash from the serialized wire payload
      - Applying cache_eligible to enable Anthropic prompt caching when the
        backend supports it
      - Emitting CloudWatch metrics (BedrockProvider only)
      - Retrying on throttling per Section 22 DW-005x taxonomy
    """
    model_config = ConfigDict(extra="forbid")

    # --- Model routing ---------------------------------------------------
    model: str = Field(
        ...,
        description="Model identifier. AnthropicProvider uses Anthropic IDs "
                    "(e.g. 'claude-sonnet-4-5'). BedrockProvider maps to the "
                    "equivalent Bedrock model ARN internally.",
    )
    execution_tier: ExecutionTier = ExecutionTier.SONNET

    # --- Prompt content --------------------------------------------------
    system_prompt: str = Field(
        ...,
        description="System prompt. Typically versioned agent YAML + assembled "
                    "organizational context. Cache-eligible when "
                    "cache_eligible=True and the backend supports it.",
    )
    messages: list[Message] = Field(
        ...,
        description="Conversation history. Usually a single user message for "
                    "initial council invocation; may include prior turns for "
                    "multi-step reasoning.",
        min_length=1,
    )

    # --- Generation controls --------------------------------------------
    max_tokens: int = Field(4096, ge=1, le=200_000)
    temperature: float = Field(0.1, ge=0.0, le=1.0)
    stop_sequences: list[str] = Field(default_factory=list)

    # --- Caching --------------------------------------------------------
    cache_eligible: bool = Field(
        False,
        description="When True, the provider writes system_prompt to the "
                    "Anthropic prompt cache on first call and reads from "
                    "cache thereafter. Driven by the prompt YAML.",
    )

    # --- Audit trail (required for Section 21 telemetry) ----------------
    prompt_name: str = Field(
        ...,
        description="Prompt YAML name, e.g. 'coding'. Recorded per Section 21.",
    )
    prompt_version: str = Field(
        ...,
        description="Prompt YAML version, e.g. '1.4.2'. Pinned per call for "
                    "reproducibility.",
    )
    agent_name: str = Field(
        ...,
        description="Which council agent made the call (intake, extraction, "
                    "coding, risk, validation, documentation).",
    )
    operation_id: str = Field(
        ...,
        description="engagement_id or pipeline_run_id. Correlates the call to "
                    "the operation audit trail.",
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class LLMResponse(BaseModel):
    """Provider-agnostic response envelope.

    Fields map directly to Section 21 LLM call telemetry. The audit_trail
    node reads from this envelope when writing to the audit table - no
    provider-specific parsing needed downstream.
    """
    model_config = ConfigDict(extra="forbid")

    # --- Content --------------------------------------------------------
    completion: str
    stop_reason: StopReason

    # --- Token accounting (Section 21 + billing per Section 08) ---------
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(
        default=0,
        ge=0,
        description="Tokens served from prompt cache at ~10 percent cost. "
                    "Zero if cache_eligible=False or cache miss.",
    )
    cache_write_tokens: int = Field(
        default=0,
        ge=0,
        description="Tokens written TO prompt cache. Charged once; subsequent "
                    "reads are cache_read_tokens.",
    )

    # --- Execution metadata ---------------------------------------------
    model: str = Field(
        ...,
        description="Actual model invoked. May differ from request.model if "
                    "the provider applied routing or fallback.",
    )
    latency_ms: int = Field(ge=0)
    guardrail_action: Literal["none", "blocked", "modified"] | None = Field(
        default=None,
        description="None if guardrails not configured (Anthropic direct); "
                    "otherwise records AWS Guardrails intervention per "
                    "Section 21.",
    )

    # --- Audit hashes (content NOT logged per Section 21) ---------------
    prompt_hash: str = Field(
        ...,
        description="SHA-256 of the assembled prompt sent to the provider. "
                    "Section 21 forbids logging prompt content; hashes allow "
                    "audit and anomaly detection.",
        min_length=64,
        max_length=64,
    )
    completion_hash: str = Field(
        ...,
        description="SHA-256 of the completion returned by the provider.",
        min_length=64,
        max_length=64,
    )

    # --- Computed helpers ------------------------------------------------
    @property
    def total_tokens(self) -> int:
        """For billing reconciliation per AC-14."""
        return self.prompt_tokens + self.completion_tokens

    @property
    def cache_hit(self) -> bool:
        """Feeds the DarwinBedrock/CacheHitRate metric (Section 21)."""
        return self.cache_read_tokens > 0


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMProvider(Protocol):
    """Every LLM backend implements this.

    Contract:
      - complete() is async; sync would block the LangGraph event loop.
      - complete() MUST return a fully-populated LLMResponse including
        prompt_hash and completion_hash computed from the wire payload.
      - Providers MUST NOT log prompt or completion content - hashes only.
      - Retry logic and CloudWatch metric emission are provider-internal,
        not part of the interface.

    @runtime_checkable enables isinstance(x, LLMProvider) at runtime for
    test fakes and fallback wiring.
    """

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send one non-streaming LLM invocation and return its envelope.

        MUST raise LLMError (or a subclass) on failure. MUST NOT return
        partial or null responses - downstream nodes rely on required
        fields being populated.
        """
        ...
