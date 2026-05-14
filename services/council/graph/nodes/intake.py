"""Intake node — classify the request and produce a structured plan.

Pure reasoning. No tools. Output is a JSON object parsed into IntakePlan.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from llm import LLMRequest, get_provider
from prompts import get_prompt

from graph.state import CouncilState, GraphEvent, IntakePlan

NODE_NAME = "intake"


def _parse_plan(raw: str) -> IntakePlan:
    """Parse the model's JSON response into an IntakePlan dict.

    Be lenient — strip code fences if the model produced any, fall back to
    a sensible default if parsing fails entirely.
    """
    text = raw.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` fencing
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Fall through to a safe default so the graph doesn't crash on a bad JSON output
        return IntakePlan(
            intent="exploratory",
            requires_tools=True,
            entities={},
            plan=[],
            notes=f"Intake failed to produce valid JSON; raw: {text[:200]}",
        )

    return IntakePlan(
        intent=parsed.get("intent", "exploratory"),
        requires_tools=bool(parsed.get("requires_tools", True)),
        entities=parsed.get("entities") or {},
        plan=parsed.get("plan") or [],
        notes=parsed.get("notes") or "",
    )


async def intake_node(state: CouncilState) -> dict[str, Any]:
    """Run the intake node. Returns partial state updates."""
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

    request = LLMRequest(
        messages=[{"role": "user", "content": state["user_message"]}],
        system=prompt.body,
        tools=[],
        agent=NODE_NAME,
        prompt_version=prompt.versioned_id,
    )

    raw_text = ""
    async for event in provider.stream(request):
        if event.type == "text":
            raw_text += event.data["text"]
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

    plan = _parse_plan(raw_text)

    duration_ms = int((time.time() - started_at) * 1000)
    events.append(GraphEvent(
        type="node_end",
        node=NODE_NAME,
        data={
            "duration_ms": duration_ms,
            "plan": plan,
        },
    ).to_dict())

    return {
        "intake_plan": plan,
        "intake_raw_response": raw_text,
        "events": events,
    }
