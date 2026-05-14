"""DynamoDB implementation of StorageBackend.

Single-table design on the 'darwin-workbench' table.

Key schema:
  pk  = entity prefix + ID   e.g. SESSION#sess_abc123
  sk  = entity type + seq    e.g. MESSAGE#0004, AUDIT#0012, TOOL#toolu_xyz

GSI1 (for listing sessions by user):
  gsi1pk = USER#<user_id>
  gsi1sk = updated_at (epoch ms, numeric) — sorted newest first

All items carry an 'entity_type' attribute for filtering.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from storage.base import StorageBackend
from storage.models import (
    AuditEvent,
    ContentBlock,
    Message,
    PromptVersion,
    Session,
    ToolCall,
)

def _get_table_name() -> str:
    return os.getenv("DYNAMODB_TABLE", "darwin-workbench")

def _get_region() -> str:
    return os.getenv("AWS_REGION", "us-east-1")


def _to_ddb(obj: Any) -> Any:
    """Recursively convert floats to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_ddb(v) for v in obj]
    return obj


def _from_ddb(obj: Any) -> Any:
    """Recursively convert Decimal back to int/float."""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_ddb(v) for v in obj]
    return obj


def _seq(n: int) -> str:
    """Zero-padded sequence string for sort key ordering."""
    return f"{n:08d}"


class DynamoDBBackend(StorageBackend):
    """AWS DynamoDB single-table backend."""

    name = "dynamodb"

    def __init__(
        self,
        table_name: str | None = None,
        region: str | None = None,
    ) -> None:
        self._table_name = table_name or _get_table_name()
        self._region = region or _get_region()
        self._table = None

    async def initialize(self) -> None:
        dynamodb = boto3.resource("dynamodb", region_name=self._region)
        self._table = dynamodb.Table(self._table_name)

    async def close(self) -> None:
        pass  # boto3 resource manages its own connection pool

    def _tbl(self):
        if self._table is None:
            raise RuntimeError("DynamoDBBackend.initialize() not called")
        return self._table

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def create_session(self, session: Session) -> Session:
        item = {
            "pk": f"SESSION#{session.session_id}",
            "sk": "META",
            "entity_type": "session",
            "gsi1pk": f"USER#{session.user_id}",
            "gsi1sk": Decimal(session.updated_at),
            **_to_ddb({
                "session_id": session.session_id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "user_id": session.user_id,
                "workspace": session.workspace,
                "environment": session.environment,
                "status": session.status,
                "title": session.title,
            }),
        }
        self._tbl().put_item(Item=item)
        return session

    async def get_session(self, session_id: str) -> Session | None:
        resp = self._tbl().get_item(
            Key={"pk": f"SESSION#{session_id}", "sk": "META"}
        )
        item = resp.get("Item")
        if not item:
            return None
        return _item_to_session(item)

    async def update_session(self, session: Session) -> None:
        self._tbl().update_item(
            Key={"pk": f"SESSION#{session.session_id}", "sk": "META"},
            UpdateExpression="SET #s = :s, updated_at = :u, gsi1sk = :u, title = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": session.status,
                ":u": Decimal(session.updated_at),
                ":t": session.title,
            },
        )

    async def list_sessions(self, user_id: str, limit: int = 50) -> list[Session]:
        resp = self._tbl().query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"USER#{user_id}"),
            ScanIndexForward=False,  # newest first
            Limit=limit,
        )
        return [_item_to_session(i) for i in resp.get("Items", [])]

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def append_message(self, message: Message) -> Message:
        item = {
            "pk": f"SESSION#{message.session_id}",
            "sk": f"MESSAGE#{_seq(message.sequence)}",
            "entity_type": "message",
            **_to_ddb({
                "message_id": message.message_id,
                "session_id": message.session_id,
                "sequence": message.sequence,
                "role": message.role,
                "content": [b.to_dict() for b in message.content],
                "created_at": message.created_at,
            }),
        }
        self._tbl().put_item(Item=item)
        return message

    async def list_messages(self, session_id: str) -> list[Message]:
        resp = self._tbl().query(
            KeyConditionExpression=(
                Key("pk").eq(f"SESSION#{session_id}") &
                Key("sk").begins_with("MESSAGE#")
            ),
            ScanIndexForward=True,
        )
        return [_item_to_message(i) for i in resp.get("Items", [])]

    # ------------------------------------------------------------------
    # Audit events
    # ------------------------------------------------------------------

    async def append_audit(self, event: AuditEvent) -> AuditEvent:
        item = {
            "pk": f"SESSION#{event.session_id}",
            "sk": f"AUDIT#{_seq(event.sequence)}",
            "entity_type": "audit_event",
            **_to_ddb({
                "event_id": event.event_id,
                "session_id": event.session_id,
                "message_id": event.message_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "layer": event.layer,
                "status": event.status,
                "payload": event.payload,
                "duration_ms": event.duration_ms,
                "created_at": event.created_at,
            }),
        }
        self._tbl().put_item(Item=item)
        return event

    async def list_audit(self, session_id: str) -> list[AuditEvent]:
        resp = self._tbl().query(
            KeyConditionExpression=(
                Key("pk").eq(f"SESSION#{session_id}") &
                Key("sk").begins_with("AUDIT#")
            ),
            ScanIndexForward=True,
        )
        return [_item_to_audit(i) for i in resp.get("Items", [])]

    # ------------------------------------------------------------------
    # Tool calls
    # ------------------------------------------------------------------

    async def start_tool_call(self, call: ToolCall) -> ToolCall:
        item = {
            "pk": f"SESSION#{call.session_id}",
            "sk": f"TOOL#{call.tool_call_id}",
            "entity_type": "tool_call",
            **_to_ddb({
                "tool_call_id": call.tool_call_id,
                "session_id": call.session_id,
                "message_id": call.message_id,
                "tool_name": call.tool_name,
                "platform": call.platform,
                "input": call.input,
                "output": call.output,
                "is_error": call.is_error,
                "duration_ms": call.duration_ms,
                "started_at": call.started_at,
                "completed_at": call.completed_at,
            }),
        }
        self._tbl().put_item(Item=item)
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

        # Scan for the tool call row by sk — acceptable for local dev;
        # add a GSI on tool_call_id for production at scale.
        scan_resp = self._tbl().scan(
            FilterExpression="sk = :sk",
            ExpressionAttributeValues={":sk": f"TOOL#{tool_call_id}"},
            Limit=10,
        )
        items = scan_resp.get("Items", [])
        if not items:
            return

        pk = items[0]["pk"]
        self._tbl().update_item(
            Key={"pk": pk, "sk": f"TOOL#{tool_call_id}"},
            UpdateExpression=(
                "SET #out = :out, is_error = :e, "
                "duration_ms = :d, completed_at = :c"
            ),
            ExpressionAttributeNames={"#out": "output"},
            ExpressionAttributeValues={
                ":out": _to_ddb(output) if output is not None else None,
                ":e": is_error,
                ":d": duration_ms,
                ":c": Decimal(completed_at),
            },
        )

    async def list_tool_calls(self, session_id: str) -> list[ToolCall]:
        resp = self._tbl().query(
            KeyConditionExpression=(
                Key("pk").eq(f"SESSION#{session_id}") &
                Key("sk").begins_with("TOOL#")
            ),
        )
        return [_item_to_tool_call(i) for i in resp.get("Items", [])]

    # ------------------------------------------------------------------
    # Prompt versions
    # ------------------------------------------------------------------

    async def register_prompt_version(self, version: PromptVersion) -> PromptVersion:
        item = {
            "pk": f"PROMPT#{version.versioned_id}",
            "sk": "META",
            "entity_type": "prompt_version",
            **_to_ddb({
                "versioned_id": version.versioned_id,
                "agent": version.agent,
                "version": version.version,
                "body_hash": version.body_hash,
                "source_path": version.source_path,
                "first_seen_at": version.first_seen_at,
            }),
        }
        # Conditional write — only insert if it doesn't exist yet
        try:
            self._tbl().put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
        except self._tbl().meta.client.exceptions.ConditionalCheckFailedException:
            pass  # Already registered — idempotent
        return version


# ------------------------------------------------------------------
# Row → dataclass mappers
# ------------------------------------------------------------------

def _item_to_session(item: dict) -> Session:
    d = _from_ddb(item)
    return Session(
        session_id=d["session_id"],
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        user_id=d["user_id"],
        workspace=d["workspace"],
        environment=d["environment"],
        status=d["status"],
        title=d.get("title"),
    )


def _item_to_message(item: dict) -> Message:
    d = _from_ddb(item)
    blocks = [ContentBlock(**b) for b in d["content"]]
    return Message(
        message_id=d["message_id"],
        session_id=d["session_id"],
        sequence=d["sequence"],
        role=d["role"],
        content=blocks,
        created_at=d["created_at"],
    )


def _item_to_audit(item: dict) -> AuditEvent:
    d = _from_ddb(item)
    return AuditEvent(
        event_id=d["event_id"],
        session_id=d["session_id"],
        message_id=d.get("message_id"),
        sequence=d["sequence"],
        event_type=d["event_type"],
        layer=d["layer"],
        status=d["status"],
        payload=d["payload"],
        duration_ms=d.get("duration_ms"),
        created_at=d["created_at"],
    )


def _item_to_tool_call(item: dict) -> ToolCall:
    d = _from_ddb(item)
    return ToolCall(
        tool_call_id=d["tool_call_id"],
        session_id=d["session_id"],
        message_id=d["message_id"],
        tool_name=d["tool_name"],
        platform=d["platform"],
        input=d["input"],
        output=d.get("output"),
        is_error=d["is_error"],
        duration_ms=d.get("duration_ms"),
        started_at=d["started_at"],
        completed_at=d.get("completed_at"),
    )
