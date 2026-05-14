"""Synthesis node — produce the user-facing response.

Sees intake's classification and extraction's tool outputs. Streams text
back through events. No tools.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from llm import LLMRequest, get_provider
from prompts import get_prompt

from graph.state import CouncilState, GraphEvent

NODE_NAME = "synthesis"


def _format_context(state: CouncilState) -> str:
    """Build the user-turn message that gives synthesis everything it needs."""
    user_msg = state["user_message"]
    plan = state.get("intake_plan") or {}
    tool_calls = state.get("tool_calls") or []

    parts = [
        f"USER ORIGINAL REQUEST:\n{user_msg}",
        f"\nINTAKE CLASSIFICATION:\n{json.dumps(plan, indent=2)}",
    ]

    if tool_calls:
        parts.append("\nEXTRACTION RESULTS — tool calls made and their outputs:")
        for i, tc in enumerate(tool_calls, 1):
            parts.append(f"\n[{i}] {tc['tool_name']}({json.dumps(tc['input'])})")
            if tc["is_error"]:
                parts.append(f"    ERROR: {json.dumps(tc['output'])[:500]}")
            else:
                # Truncate enormous outputs to keep the context manageable
                out_text = json.dumps(tc["output"])
                if len(out_text) > 4000:
                    out_text = out_text[:4000] + "... [truncated]"
                parts.append(f"    OUTPUT: {out_text}")
    else:
        parts.append("\nEXTRACTION RESULTS: (none — no tools were called)")

    parts.append("\nNow write the response to the user.")
    return "\n".join(parts)


async def synthesis_node(state: CouncilState) -> dict[str, Any]:
    """Run the synthesis node. Streams text via events."""
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

    context_message = _format_context(state)

    request = LLMRequest(
        messages=[{"role": "user", "content": context_message}],
        system=prompt.body,
        tools=[],
        agent=NODE_NAME,
        prompt_version=prompt.versioned_id,
    )

    full_text = ""
    async for event in provider.stream(request):
        if event.type == "text":
            full_text += event.data["text"]
            events.append(GraphEvent(
                type="text",
                node=NODE_NAME,
                data={"text": event.data["text"]},
            ).to_dict())
        elif event.type == "turn_end":
            events.append(GraphEvent(
                type="llm_turn_end",
                node=NODE_NAME,
                data={
                    "agent": event.agent,
                    "prompt_version": event.prompt_version,
                    "provider": event.provider,
                    "model": event.model,
                    "stop_reason": event.data.get("stop_reason"),
                    "usage": event.data.get("usage", {}),
                },
            ).to_dict())

    duration_ms = int((time.time() - started_at) * 1000)
    events.append(GraphEvent(
        type="node_end",
        node=NODE_NAME,
        data={"duration_ms": duration_ms},
    ).to_dict())

    return {
        "final_response": full_text,
        "events": events,
    }
