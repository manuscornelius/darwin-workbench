"""Extraction node — execute MCP tool calls according to the intake plan.

This is the agent loop, scoped by the plan from intake. Tools are provided
by the MCP client (injected via state at graph build time).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from llm import LLMRequest, get_provider
from prompts import get_prompt

from graph.state import CouncilState, GraphEvent

NODE_NAME = "extraction"
MAX_ITERATIONS = 10


# The MCP client is injected at graph-build time and stored module-level so
# the node function (which LangGraph calls with only state) can reach it.
_mcp_client: Any = None


def set_mcp_client(client: Any) -> None:
    """Wire the MCP client. Called once during graph construction."""
    global _mcp_client
    _mcp_client = client


def _format_plan_for_prompt(plan: dict[str, Any], user_message: str) -> str:
    """Render the intake plan as a user-turn message for extraction's LLM call."""
    entities = plan.get("entities") or {}
    steps = plan.get("plan") or []
    notes = plan.get("notes") or ""

    parts = [
        f"USER REQUEST:\n{user_message}",
        f"\nINTENT: {plan.get('intent', 'exploratory')}",
    ]
    if entities:
        parts.append(f"ENTITIES: {json.dumps(entities)}")
    if steps:
        parts.append("PLAN:")
        for i, step in enumerate(steps, 1):
            parts.append(f"  {i}. {step}")
    if notes:
        parts.append(f"NOTES: {notes}")
    parts.append("\nExecute the plan. Make tool calls only — no prose.")
    return "\n".join(parts)


async def extraction_node(state: CouncilState) -> dict[str, Any]:
    """Run the extraction node. Returns partial state updates."""
    provider = get_provider(os.getenv("LLM_PROVIDER", "anthropic_direct"))
    prompt = get_prompt(NODE_NAME)

    started_at = time.time()
    events: list[dict[str, Any]] = [
        GraphEvent(
            type="node_start",
            node=NODE_NAME,
            data={"prompt_version": prompt.versioned_id},
        ).to_dict()
    ]

    if _mcp_client is None:
        events.append(GraphEvent(
            type="node_end",
            node=NODE_NAME,
            data={"duration_ms": 0, "skipped_reason": "MCP client not initialised"},
        ).to_dict())
        return {"events": events, "extraction_messages": [], "tool_calls": []}

    plan = state.get("intake_plan") or {}
    plan_message = _format_plan_for_prompt(plan, state["user_message"])

    messages: list[dict[str, Any]] = [{"role": "user", "content": plan_message}]
    tool_calls_log: list[dict[str, Any]] = []
    pending_started: dict[str, float] = {}

    for _ in range(MAX_ITERATIONS):
        request = LLMRequest(
            messages=messages,
            system=prompt.body,
            tools=_mcp_client.tools,
            agent=NODE_NAME,
            prompt_version=prompt.versioned_id,
        )

        stop_reason = "end_turn"
        assistant_blocks: list[dict[str, Any]] = []

        async for event in provider.stream(request):
            if event.type == "tool_use_start":
                tool_id = event.data["id"]
                tool_name = event.data["name"]
                pending_started[tool_id] = time.time()
                events.append(GraphEvent(
                    type="tool_call_start",
                    node=NODE_NAME,
                    data={
                        "id": tool_id,
                        "name": tool_name,
                        "time": time.strftime("%H:%M:%S"),
                        "agent": event.agent,
                        "prompt_version": event.prompt_version,
                        "provider": event.provider,
                        "model": event.model,
                    },
                ).to_dict())

            elif event.type == "turn_end":
                stop_reason = event.data.get("stop_reason", "end_turn")
                assistant_blocks = event.data.get("stop_blocks", [])
                events.append(GraphEvent(
                    type="llm_turn_end",
                    node=NODE_NAME,
                    data={
                        "agent": event.agent,
                        "prompt_version": event.prompt_version,
                        "provider": event.provider,
                        "model": event.model,
                        "stop_reason": stop_reason,
                        "usage": event.data.get("usage", {}),
                    },
                ).to_dict())

        if assistant_blocks:
            messages.append({"role": "assistant", "content": assistant_blocks})

        if stop_reason != "tool_use":
            break

        # Execute every tool_use block
        tool_results: list[dict[str, Any]] = []
        for block in assistant_blocks:
            if block.get("type") != "tool_use":
                continue

            tool_use_id = block["id"]
            tool_name = block["name"]
            tool_input = block.get("input", {})

            try:
                result = await _mcp_client.call_tool(tool_name, tool_input)
                content = result.get("content", [])
                is_error = result.get("isError", False) or result.get("is_error", False)
            except Exception as exc:  # noqa: BLE001
                content = [{"type": "text", "text": f"Tool execution failed: {exc}"}]
                is_error = True
                result = {"content": content, "is_error": True}

            started = pending_started.pop(tool_use_id, time.time())
            duration_ms = int((time.time() - started) * 1000)
            events.append(GraphEvent(
                type="tool_call_end",
                node=NODE_NAME,
                data={
                    "id": tool_use_id,
                    "status": "error" if is_error else "success",
                    "ms": duration_ms,
                },
            ).to_dict())

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
                "is_error": is_error,
            })
            tool_calls_log.append({
                "tool_call_id": tool_use_id,
                "tool_name": tool_name,
                "input": tool_input,
                "output": result,
                "is_error": is_error,
                "duration_ms": duration_ms,
            })

        messages.append({"role": "user", "content": tool_results})

    duration_ms = int((time.time() - started_at) * 1000)
    events.append(GraphEvent(
        type="node_end",
        node=NODE_NAME,
        data={
            "duration_ms": duration_ms,
            "tool_call_count": len(tool_calls_log),
        },
    ).to_dict())

    return {
        "extraction_messages": messages,
        "tool_calls": tool_calls_log,
        "events": events,
    }
