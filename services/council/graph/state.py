"""CouncilState — the shared object that flows through the graph.

LangGraph passes this dict between nodes. Each node reads, does work, and
returns a partial dict that LangGraph merges into the running state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


Intent = Literal[
    "factual_lookup",
    "exploratory",
    "analytical",
    "general_knowledge",
    "unclear",
]


class IntakePlan(TypedDict, total=False):
    intent: Intent
    requires_tools: bool
    entities: dict[str, list[str]]
    plan: list[str]
    notes: str


def _merge_events(left: list, right: list) -> list:
    """Reducer for the events list — append-only."""
    return (left or []) + (right or [])


def _merge_tool_calls(left: list, right: list) -> list:
    return (left or []) + (right or [])


def _merge_anthropic_messages(left: list, right: list) -> list:
    """Reducer for raw Anthropic-format messages — append-only."""
    return (left or []) + (right or [])


class CouncilState(TypedDict, total=False):
    """The state object passed between nodes.

    `total=False` so each node only has to return the keys it updates.
    """

    # Input — set once when the graph is invoked
    session_id: str
    user_message: str
    history: list[dict[str, Any]]  # Prior turns in Anthropic message format

    # Filled by intake
    intake_plan: IntakePlan
    intake_raw_response: str  # The JSON string the model returned, for debugging

    # Filled by extraction
    extraction_messages: Annotated[list[dict[str, Any]], _merge_anthropic_messages]
    tool_calls: Annotated[list[dict[str, Any]], _merge_tool_calls]

    # Filled by synthesis
    final_response: str

    # Accumulated across all nodes — streamed to the browser
    events: Annotated[list[dict[str, Any]], _merge_events]


@dataclass
class GraphEvent:
    """One event emitted by a node during execution.

    These are buffered into state.events and the main.py SSE driver picks
    them up to forward to the browser.
    """

    type: str  # e.g. "node_start", "node_end", "text", "tool_call_start"
    data: dict[str, Any]
    node: str  # which node emitted this

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "node": self.node, **self.data}
