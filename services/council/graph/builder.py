"""Build and run the council graph.

Three nodes — intake → (conditional) → extraction → synthesis. Or, if
intake decides no tools are needed: intake → synthesis.

`run_council` is the entry point — it streams events to the caller as
nodes execute. The caller (main.py) forwards them as SSE to the browser.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from langgraph.graph import END, START, StateGraph

from graph.nodes import extraction_node, intake_node, synthesis_node
from graph.nodes.extraction import set_mcp_client
from graph.state import CouncilState


def _route_after_intake(state: CouncilState) -> str:
    """Conditional edge: skip extraction if no tools are needed."""
    plan = state.get("intake_plan") or {}
    if plan.get("requires_tools", True):
        return "extraction"
    return "synthesis"


def build_council_graph(mcp_client: Any):
    """Build and compile the council StateGraph.

    `mcp_client` is wired into the extraction node module-level. Call this
    once at app startup.
    """
    set_mcp_client(mcp_client)

    graph = StateGraph(CouncilState)
    graph.add_node("intake", intake_node)
    graph.add_node("extraction", extraction_node)
    graph.add_node("synthesis", synthesis_node)

    graph.add_edge(START, "intake")
    graph.add_conditional_edges(
        "intake",
        _route_after_intake,
        {"extraction": "extraction", "synthesis": "synthesis"},
    )
    graph.add_edge("extraction", "synthesis")
    graph.add_edge("synthesis", END)

    return graph.compile()


async def run_council(
    graph: Any,
    user_message: str,
    session_id: str,
    history: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the graph and yield events as they arrive.

    Yields the same dict shape the browser expects (`type` plus event-specific
    keys, with `node` indicating which graph node produced it).
    """
    initial_state: CouncilState = {
        "session_id": session_id,
        "user_message": user_message,
        "history": history or [],
        "events": [],
        "tool_calls": [],
    }

    # LangGraph's astream with stream_mode="values" emits the state after
    # each node. We diff the events list to emit only the newly added events.
    emitted = 0
    final_state: dict[str, Any] = {}
    async for state in graph.astream(initial_state, stream_mode="values"):
        final_state = state
        events = state.get("events") or []
        for event in events[emitted:]:
            yield event
        emitted = len(events)

    # Yield a final state marker so the caller knows what was produced overall
    yield {
        "type": "graph_complete",
        "node": "graph",
        "intake_plan": final_state.get("intake_plan"),
        "tool_calls": final_state.get("tool_calls", []),
        "final_response": final_state.get("final_response", ""),
    }
