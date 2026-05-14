"""Abstract repository interfaces.

Each concrete storage backend (sqlite, dynamodb) implements StorageBackend.
The agent loop calls backend methods — never raw SQL or boto3 — so swapping
backends is a registry change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from storage.models import AuditEvent, Message, PromptVersion, Session, ToolCall


class StorageBackend(ABC):
    """Single-interface storage. All five entity types in one class because
    they share a transactional context in practice (one session has many
    messages, audit events, and tool calls, written interleaved)."""

    name: str = "unspecified"

    @abstractmethod
    async def initialize(self) -> None:
        """Run any one-time setup (schema migration, table creation)."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""

    # Sessions ---------------------------------------------------------

    @abstractmethod
    async def create_session(self, session: Session) -> Session:
        ...

    @abstractmethod
    async def get_session(self, session_id: str) -> Session | None:
        ...

    @abstractmethod
    async def update_session(self, session: Session) -> None:
        ...

    @abstractmethod
    async def list_sessions(self, user_id: str, limit: int = 50) -> list[Session]:
        ...

    # Messages ---------------------------------------------------------

    @abstractmethod
    async def append_message(self, message: Message) -> Message:
        ...

    @abstractmethod
    async def list_messages(self, session_id: str) -> list[Message]:
        ...

    # Audit events -----------------------------------------------------

    @abstractmethod
    async def append_audit(self, event: AuditEvent) -> AuditEvent:
        ...

    @abstractmethod
    async def list_audit(self, session_id: str) -> list[AuditEvent]:
        ...

    # Tool calls -------------------------------------------------------

    @abstractmethod
    async def start_tool_call(self, call: ToolCall) -> ToolCall:
        ...

    @abstractmethod
    async def complete_tool_call(
        self,
        tool_call_id: str,
        output: dict[str, Any] | None,
        is_error: bool,
        duration_ms: int,
    ) -> None:
        ...

    @abstractmethod
    async def list_tool_calls(self, session_id: str) -> list[ToolCall]:
        ...

    # Prompt versions --------------------------------------------------

    @abstractmethod
    async def register_prompt_version(self, version: PromptVersion) -> PromptVersion:
        """Insert if new, return existing if a row with the same versioned_id exists."""
