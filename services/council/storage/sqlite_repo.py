"""SQLite implementation of StorageBackend.

Single file at services/council/data/darwin.db. Schema is created on first
run via initialize().
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import aiosqlite

from storage.base import StorageBackend
from storage.models import (
    AuditEvent,
    ContentBlock,
    Message,
    PromptVersion,
    Session,
    ToolCall,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    workspace TEXT NOT NULL,
    environment TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_updated
    ON sessions(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,  -- JSON-encoded list of ContentBlock dicts
    created_at INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session_seq
    ON messages(session_id, sequence);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_id TEXT,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    layer TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,  -- JSON-encoded dict
    duration_ms INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_session_seq
    ON audit_events(session_id, sequence);

CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    input TEXT NOT NULL,
    output TEXT,
    is_error INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    started_at INTEGER NOT NULL,
    completed_at INTEGER,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_session
    ON tool_calls(session_id);

CREATE INDEX IF NOT EXISTS idx_tool_calls_name_started
    ON tool_calls(tool_name, started_at DESC);

CREATE TABLE IF NOT EXISTS prompt_versions (
    versioned_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    version TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    source_path TEXT NOT NULL,
    first_seen_at INTEGER NOT NULL
);
"""


class SQLiteBackend(StorageBackend):
    """File-backed SQLite. aiosqlite serialises all writes to one connection,
    which is fine for local single-process use."""

    name = "sqlite"

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            data_dir = Path(__file__).parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "darwin.db")
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteBackend.initialize() not called")
        return self._db

    # Sessions ---------------------------------------------------------

    async def create_session(self, session: Session) -> Session:
        await self._conn().execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.session_id, session.created_at, session.updated_at,
                session.user_id, session.workspace, session.environment,
                session.status, session.title,
            ),
        )
        await self._conn().commit()
        return session

    async def get_session(self, session_id: str) -> Session | None:
        async with self._conn().execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_session(row) if row else None

    async def update_session(self, session: Session) -> None:
        await self._conn().execute(
            "UPDATE sessions SET updated_at=?, status=?, title=? WHERE session_id=?",
            (session.updated_at, session.status, session.title, session.session_id),
        )
        await self._conn().commit()

    async def list_sessions(self, user_id: str, limit: int = 50) -> list[Session]:
        async with self._conn().execute(
            "SELECT * FROM sessions WHERE user_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_session(r) for r in rows]

    # Messages ---------------------------------------------------------

    async def append_message(self, message: Message) -> Message:
        await self._conn().execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
            (
                message.message_id, message.session_id, message.sequence,
                message.role,
                json.dumps([b.to_dict() for b in message.content]),
                message.created_at,
            ),
        )
        await self._conn().commit()
        return message

    async def list_messages(self, session_id: str) -> list[Message]:
        async with self._conn().execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY sequence",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_message(r) for r in rows]

    # Audit events -----------------------------------------------------

    async def append_audit(self, event: AuditEvent) -> AuditEvent:
        await self._conn().execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.event_id, event.session_id, event.message_id, event.sequence,
                event.event_type, event.layer, event.status,
                json.dumps(event.payload), event.duration_ms, event.created_at,
            ),
        )
        await self._conn().commit()
        return event

    async def list_audit(self, session_id: str) -> list[AuditEvent]:
        async with self._conn().execute(
            "SELECT * FROM audit_events WHERE session_id = ? ORDER BY sequence",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_audit(r) for r in rows]

    # Tool calls -------------------------------------------------------

    async def start_tool_call(self, call: ToolCall) -> ToolCall:
        await self._conn().execute(
            "INSERT INTO tool_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                call.tool_call_id, call.session_id, call.message_id, call.tool_name,
                call.platform, json.dumps(call.input),
                json.dumps(call.output) if call.output is not None else None,
                int(call.is_error), call.duration_ms,
                call.started_at, call.completed_at,
            ),
        )
        await self._conn().commit()
        return call

    async def complete_tool_call(
        self,
        tool_call_id: str,
        output: dict[str, Any] | None,
        is_error: bool,
        duration_ms: int,
    ) -> None:
        import time as _t
        completed_at = int(_t.time() * 1000)
        await self._conn().execute(
            "UPDATE tool_calls SET output=?, is_error=?, duration_ms=?, completed_at=? "
            "WHERE tool_call_id=?",
            (
                json.dumps(output) if output is not None else None,
                int(is_error), duration_ms, completed_at, tool_call_id,
            ),
        )
        await self._conn().commit()

    async def list_tool_calls(self, session_id: str) -> list[ToolCall]:
        async with self._conn().execute(
            "SELECT * FROM tool_calls WHERE session_id = ? ORDER BY started_at",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_tool_call(r) for r in rows]

    # Prompt versions --------------------------------------------------

    async def register_prompt_version(self, version: PromptVersion) -> PromptVersion:
        # Idempotent insert — keep the first sighting
        await self._conn().execute(
            "INSERT OR IGNORE INTO prompt_versions VALUES (?, ?, ?, ?, ?, ?)",
            (
                version.versioned_id, version.agent, version.version,
                version.body_hash, version.source_path, version.first_seen_at,
            ),
        )
        await self._conn().commit()
        return version


# ---------------------------------------------------------------------------
# Row → dataclass mappers (kept private to this module)
# ---------------------------------------------------------------------------

def _row_to_session(row: Any) -> Session:
    return Session(
        session_id=row[0], created_at=row[1], updated_at=row[2],
        user_id=row[3], workspace=row[4], environment=row[5],
        status=row[6], title=row[7],
    )


def _row_to_message(row: Any) -> Message:
    blocks_raw = json.loads(row[4])
    blocks = [ContentBlock(**b) for b in blocks_raw]
    return Message(
        message_id=row[0], session_id=row[1], sequence=row[2],
        role=row[3], content=blocks, created_at=row[5],
    )


def _row_to_audit(row: Any) -> AuditEvent:
    return AuditEvent(
        event_id=row[0], session_id=row[1], message_id=row[2], sequence=row[3],
        event_type=row[4], layer=row[5], status=row[6],
        payload=json.loads(row[7]), duration_ms=row[8], created_at=row[9],
    )


def _row_to_tool_call(row: Any) -> ToolCall:
    return ToolCall(
        tool_call_id=row[0], session_id=row[1], message_id=row[2],
        tool_name=row[3], platform=row[4],
        input=json.loads(row[5]),
        output=json.loads(row[6]) if row[6] else None,
        is_error=bool(row[7]), duration_ms=row[8],
        started_at=row[9], completed_at=row[10],
    )
