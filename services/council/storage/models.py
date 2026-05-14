"""CIM dataclasses — the canonical shape of everything the council produces.

Storage-agnostic. The repository layer is responsible for round-tripping
these to whatever backend is configured.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    """Unix epoch in milliseconds — single source of truth for timestamps."""
    return int(time.time() * 1000)


def _new_id(prefix: str) -> str:
    """Prefixed UUID4, easier to recognise in logs and DBs."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """A single chat session — one browser tab, one starting prompt."""

    session_id: str = field(default_factory=lambda: _new_id("sess"))
    created_at: int = field(default_factory=_now_ms)
    updated_at: int = field(default_factory=_now_ms)
    user_id: str = "manus"
    workspace: str = "Column5"
    environment: str = "Darwin_Connect"
    status: Literal["active", "completed", "errored"] = "active"
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContentBlock:
    """A single block inside a Message.content list.

    Mirrors Anthropic's block model: text | tool_use | tool_result.
    Storing this shape verbatim means the conversation can be replayed
    against the API without translation.
    """

    type: Literal["text", "tool_use", "tool_result"]
    # text blocks
    text: str | None = None
    # tool_use blocks
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    # tool_result blocks
    tool_use_id: str | None = None
    content: list[dict[str, Any]] | None = None
    is_error: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Message:
    """One turn of conversation."""

    message_id: str = field(default_factory=lambda: _new_id("msg"))
    session_id: str = ""
    sequence: int = 0
    role: Literal["user", "assistant"] = "user"
    content: list[ContentBlock] = field(default_factory=list)
    created_at: int = field(default_factory=_now_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "role": self.role,
            "content": [b.to_dict() for b in self.content],
            "created_at": self.created_at,
        }


@dataclass
class AuditEvent:
    """Observable event in the session — the right-panel feed."""

    event_id: str = field(default_factory=lambda: _new_id("evt"))
    session_id: str = ""
    message_id: str | None = None
    sequence: int = 0
    event_type: str = ""  # "tool_call" | "llm_turn" | "prompt_loaded" | "error"
    layer: str = ""  # "mcp" | "llm" | "system"
    status: Literal["pending", "success", "error"] = "pending"
    payload: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None
    created_at: int = field(default_factory=_now_ms)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolCall:
    """First-class record of every MCP call."""

    tool_call_id: str = ""  # = Anthropic's tool_use_id
    session_id: str = ""
    message_id: str = ""
    tool_name: str = ""
    platform: str = "SAP_BPC_MS"
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    is_error: bool = False
    duration_ms: int | None = None
    started_at: int = field(default_factory=_now_ms)
    completed_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PromptVersion:
    """Manifest entry for a YAML prompt version we've observed in this DB."""

    versioned_id: str  # "council@0.2.0"
    agent: str
    version: str
    body_hash: str  # SHA256 of body — detects unversioned edits
    source_path: str
    first_seen_at: int = field(default_factory=_now_ms)

    @staticmethod
    def hash_body(body: str) -> str:
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
