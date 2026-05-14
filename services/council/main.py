"""Darwin Council — local agent service driving a 3-node LangGraph.

The browser POSTs to /chat, this service runs the council graph
(intake → [conditional] extraction → synthesis), streams events as SSE,
and persists everything to SQLite via the CIM storage layer.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from graph import build_council_graph, run_council
from llm import get_provider
from prompts import get_prompt
from storage import (
    AuditEvent,
    ContentBlock,
    Message,
    PromptVersion,
    Session,
    ToolCall,
    get_storage,
)

load_dotenv()

EPM_CONNECT_URL = os.getenv("EPM_CONNECT_URL", "http://127.0.0.1:8000/mcp")
EPM_CONNECT_AUTH_TOKEN = os.getenv("EPM_CONNECT_AUTH_TOKEN", "")
COUNCIL_PORT = int(os.getenv("COUNCIL_PORT", "8001"))
LLM_PROVIDER_NAME = os.getenv("LLM_PROVIDER", "anthropic_direct")
STORAGE_PROVIDER_NAME = os.getenv("STORAGE_PROVIDER", "sqlite")

COUNCIL_PROMPT_SOURCE_TEMPLATE = "prompts/system_prompts/{name}.yaml"
COUNCIL_NODE_NAMES = ["intake", "extraction", "synthesis"]


# ---------------------------------------------------------------------------
# MCP client
# ---------------------------------------------------------------------------

class MCPClient:
    def __init__(self, url: str, auth_token: str) -> None:
        self.url = url
        self.headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._request_id = 0
        self._tools: list[dict[str, Any]] = []

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def __aenter__(self) -> "MCPClient":
        self._client = httpx.AsyncClient(timeout=60.0)
        await self.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self._client is not None
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            payload["params"] = params

        headers = dict(self.headers)
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        response = await self._client.post(self.url, json=payload, headers=headers)
        response.raise_for_status()

        if "mcp-session-id" in response.headers and not self._session_id:
            self._session_id = response.headers["mcp-session-id"]

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for line in response.text.splitlines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if "result" in data or "error" in data:
                        return data
            raise RuntimeError(f"No result in SSE response: {response.text[:200]}")
        return response.json()

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self._client is not None
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params

        headers = dict(self.headers)
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        await self._client.post(self.url, json=payload, headers=headers)

    async def initialize(self) -> None:
        init_result = await self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "darwin-council", "version": "0.1.0"},
        })
        if "error" in init_result:
            raise RuntimeError(f"MCP initialize failed: {init_result['error']}")
        await self._notify("notifications/initialized")
        tools_result = await self._send("tools/list")
        if "error" in tools_result:
            raise RuntimeError(f"tools/list failed: {tools_result['error']}")
        self._tools = tools_result["result"]["tools"]

    @property
    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t["inputSchema"],
            }
            for t in self._tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._send("tools/call", {"name": name, "arguments": arguments})
        if "error" in result:
            return {"is_error": True, "content": [{"type": "text", "text": str(result["error"])}]}
        return result["result"]


# ---------------------------------------------------------------------------
# Lifespan — set up MCP, storage, prompt registry, and the council graph
# ---------------------------------------------------------------------------

mcp_client: MCPClient | None = None
council_graph: Any = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global mcp_client, council_graph

    mcp_client = MCPClient(EPM_CONNECT_URL, EPM_CONNECT_AUTH_TOKEN)
    await mcp_client.__aenter__()

    storage = get_storage(STORAGE_PROVIDER_NAME)
    await storage.initialize()

    # Pre-register every council node's prompt version so the manifest is
    # complete before any user message arrives.
    for node_name in COUNCIL_NODE_NAMES:
        p = get_prompt(node_name)
        await storage.register_prompt_version(PromptVersion(
            versioned_id=p.versioned_id,
            agent=p.name,
            version=p.version,
            body_hash=PromptVersion.hash_body(p.body),
            source_path=COUNCIL_PROMPT_SOURCE_TEMPLATE.format(name=node_name),
        ))

    council_graph = build_council_graph(mcp_client)

    provider = get_provider(LLM_PROVIDER_NAME)
    print(f"[council] LLM provider: {provider.name}")
    print(f"[council] Storage: {storage.name}")
    print(f"[council] Council graph compiled with nodes: {COUNCIL_NODE_NAMES}")
    print(f"[council] MCP client initialized with {len(mcp_client.tools)} tools: "
          f"{[t['name'] for t in mcp_client.tools]}")
    yield
    if mcp_client:
        await mcp_client.__aexit__(None, None, None)
    await storage.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def sse(event_type: str, data: dict[str, Any]) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# ---------------------------------------------------------------------------
# /chat — run the council graph for one user message
# ---------------------------------------------------------------------------

async def chat_stream(user_message: str, session_id: str | None):
    """Drive the council graph and persist + relay every event."""
    assert mcp_client is not None
    assert council_graph is not None
    storage = get_storage(STORAGE_PROVIDER_NAME)

    next_audit_seq = 0
    session: Session | None = None
    sid: str | None = session_id

    try:
        # ----- Resolve or create session
        if session_id:
            existing = await storage.get_session(session_id)
            if not existing:
                yield sse("error", {
                    "error_type": "UnknownSession",
                    "message": f"Session {session_id} not found",
                })
                return
            session = existing
        else:
            session = Session(title=user_message[:60])
            await storage.create_session(session)
        sid = session.session_id

        yield sse("session_ready", {
            "session_id": session.session_id,
            "title": session.title,
            "created_at": session.created_at,
        })

        # ----- Replay session history for the graph
        existing_messages = await storage.list_messages(session.session_id)
        history = [
            {"role": m.role, "content": [b.to_dict() for b in m.content]}
            for m in existing_messages
        ]
        next_sequence = (existing_messages[-1].sequence + 1) if existing_messages else 0
        existing_audit = await storage.list_audit(session.session_id)
        next_audit_seq = len(existing_audit)

        # ----- Persist the new user message
        user_msg = Message(
            session_id=session.session_id,
            sequence=next_sequence,
            role="user",
            content=[ContentBlock(type="text", text=user_message)],
        )
        await storage.append_message(user_msg)
        next_sequence += 1

        # ----- Emit prompt_loaded events for every council prompt this run will use
        for node_name in COUNCIL_NODE_NAMES:
            p = get_prompt(node_name)
            source = COUNCIL_PROMPT_SOURCE_TEMPLATE.format(name=node_name)
            await storage.append_audit(AuditEvent(
                session_id=session.session_id,
                sequence=next_audit_seq,
                event_type="prompt_loaded",
                layer="system",
                status="success",
                payload={
                    "agent": p.name,
                    "version": p.versioned_id,
                    "source": source,
                },
            ))
            next_audit_seq += 1
            yield sse("prompt_loaded", {
                "agent": p.name,
                "version": p.versioned_id,
                "source": source,
            })

        # ----- Run the graph
        assistant_blocks: list[ContentBlock] = []
        # Track tool calls to persist as first-class ToolCall rows
        tool_call_starts: dict[str, dict[str, Any]] = {}  # tool_use_id -> {name, started_at_ms}

        async for event in run_council(
            council_graph,
            user_message=user_message,
            session_id=session.session_id,
            history=history,
        ):
            etype = event.get("type")
            node = event.get("node", "graph")

            # ----- Forward and persist node lifecycle events
            if etype == "node_start":
                await storage.append_audit(AuditEvent(
                    session_id=session.session_id,
                    sequence=next_audit_seq,
                    event_type="node_start",
                    layer="graph",
                    status="pending",
                    payload={"node": node, "prompt_version": event.get("prompt_version")},
                ))
                next_audit_seq += 1
                yield sse("node_start", {
                    "node": node,
                    "prompt_version": event.get("prompt_version"),
                    "time": time.strftime("%H:%M:%S"),
                })

            elif etype == "node_end":
                await storage.append_audit(AuditEvent(
                    session_id=session.session_id,
                    sequence=next_audit_seq,
                    event_type="node_end",
                    layer="graph",
                    status="success",
                    payload={
                        "node": node,
                        "duration_ms": event.get("duration_ms"),
                        "tool_call_count": event.get("tool_call_count"),
                    },
                    duration_ms=event.get("duration_ms"),
                ))
                next_audit_seq += 1
                yield sse("node_end", {
                    "node": node,
                    "duration_ms": event.get("duration_ms"),
                    "tool_call_count": event.get("tool_call_count"),
                })

            # ----- Forward text (only synthesis streams it to the user)
            elif etype == "text":
                yield sse("text", {"text": event["text"]})

            # ----- Tool calls — persist start, audit, and forward
            elif etype == "tool_call_start":
                tool_id = event["id"]
                tool_name = event["name"]
                started_at_ms = int(time.time() * 1000)
                tool_call_starts[tool_id] = {
                    "name": tool_name,
                    "started_at": started_at_ms,
                }
                await storage.start_tool_call(ToolCall(
                    tool_call_id=tool_id,
                    session_id=session.session_id,
                    message_id="",  # filled by extraction's assistant message later
                    tool_name=tool_name,
                    started_at=started_at_ms,
                ))
                await storage.append_audit(AuditEvent(
                    session_id=session.session_id,
                    sequence=next_audit_seq,
                    event_type="tool_call",
                    layer="mcp",
                    status="pending",
                    payload={
                        "tool_call_id": tool_id,
                        "tool_name": tool_name,
                        "node": node,
                    },
                ))
                next_audit_seq += 1
                yield sse("tool_call_start", {
                    "id": tool_id,
                    "name": tool_name,
                    "time": event.get("time"),
                    "node": node,
                    "prompt_version": event.get("prompt_version"),
                    "provider": event.get("provider"),
                    "model": event.get("model"),
                })

            elif etype == "tool_call_end":
                tool_id = event["id"]
                duration_ms = event.get("ms")
                status_str = event.get("status", "success")
                is_error = status_str == "error"
                await storage.complete_tool_call(
                    tool_call_id=tool_id,
                    output=None,  # full output stored in graph_complete below
                    is_error=is_error,
                    duration_ms=duration_ms or 0,
                )
                await storage.append_audit(AuditEvent(
                    session_id=session.session_id,
                    sequence=next_audit_seq,
                    event_type="tool_result",
                    layer="mcp",
                    status=status_str,
                    payload={"tool_call_id": tool_id, "node": node},
                    duration_ms=duration_ms,
                ))
                next_audit_seq += 1
                yield sse("tool_call_end", {
                    "id": tool_id,
                    "status": status_str,
                    "ms": duration_ms,
                })

            # ----- LLM turn metadata (we don't surface to UI yet, but persist it)
            elif etype == "llm_turn_end":
                await storage.append_audit(AuditEvent(
                    session_id=session.session_id,
                    sequence=next_audit_seq,
                    event_type="llm_turn",
                    layer="llm",
                    status="success",
                    payload={
                        "node": node,
                        "model": event.get("model"),
                        "provider": event.get("provider"),
                        "prompt_version": event.get("prompt_version"),
                        "stop_reason": event.get("stop_reason"),
                        "usage": event.get("usage", {}),
                    },
                ))
                next_audit_seq += 1
                yield sse("llm_turn_end", event)

            # ----- Final state from the graph — persist the assistant message and tool outputs
            elif etype == "graph_complete":
                final_response = event.get("final_response", "")
                tool_calls = event.get("tool_calls", [])

                # Build the assistant message: a single text block with the synthesis output.
                # We don't reconstruct the full Anthropic tool_use/tool_result history
                # because that lives inside the graph's extraction_messages — for
                # session resume, history replay uses our stored messages.
                if final_response:
                    asst_msg = Message(
                        session_id=session.session_id,
                        sequence=next_sequence,
                        role="assistant",
                        content=[ContentBlock(type="text", text=final_response)],
                    )
                    await storage.append_message(asst_msg)
                    next_sequence += 1

                # Backfill tool_call outputs and message_id linkage
                for tc in tool_calls:
                    await storage.complete_tool_call(
                        tool_call_id=tc["tool_call_id"],
                        output=tc.get("output"),
                        is_error=tc.get("is_error", False),
                        duration_ms=tc.get("duration_ms", 0),
                    )

        # ----- Mark session complete
        session.status = "completed"
        session.updated_at = int(time.time() * 1000)
        await storage.update_session(session)
        yield sse("done", {"session_id": session.session_id})

    except Exception as exc:  # noqa: BLE001
        error_type = type(exc).__name__
        message = str(exc)
        status_code = getattr(exc, "status_code", None)
        provider_error_type = None
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            err = body.get("error") or {}
            provider_error_type = err.get("type")
            if err.get("message"):
                message = err["message"]

        import traceback
        print(f"[council] chat_stream error: {error_type}: {message}")
        traceback.print_exc()

        try:
            if sid:
                await storage.append_audit(AuditEvent(
                    session_id=sid,
                    sequence=next_audit_seq,
                    event_type="error",
                    layer="system",
                    status="error",
                    payload={
                        "error_type": error_type,
                        "provider_error_type": provider_error_type,
                        "status_code": status_code,
                        "message": message,
                    },
                ))
        except Exception:  # noqa: BLE001
            pass

        yield sse("error", {
            "error_type": error_type,
            "provider_error_type": provider_error_type,
            "status_code": status_code,
            "message": message,
        })


@app.post("/chat")
async def chat(req: ChatRequest):
    return StreamingResponse(
        chat_stream(req.message, req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/sessions")
async def list_sessions(user_id: str = "manus", limit: int = 50):
    storage = get_storage(STORAGE_PROVIDER_NAME)
    sessions = await storage.list_sessions(user_id, limit)
    return [s.to_dict() for s in sessions]


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    storage = get_storage(STORAGE_PROVIDER_NAME)
    session = await storage.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await storage.list_messages(session_id)
    audit = await storage.list_audit(session_id)
    tool_calls = await storage.list_tool_calls(session_id)
    return {
        "session": session.to_dict(),
        "messages": [m.to_dict() for m in messages],
        "audit": [e.to_dict() for e in audit],
        "tool_calls": [t.to_dict() for t in tool_calls],
    }


@app.get("/health")
async def health():
    storage = get_storage(STORAGE_PROVIDER_NAME)
    return {
        "status": "ok",
        "provider": LLM_PROVIDER_NAME,
        "storage": storage.name,
        "graph_nodes": COUNCIL_NODE_NAMES,
        "tools": [t["name"] for t in mcp_client.tools] if mcp_client else [],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=COUNCIL_PORT)
