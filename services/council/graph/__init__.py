"""LangGraph council — three-node graph (intake → extraction → synthesis).

The graph replaces the single-loop agent in main.py. It exposes one entry
point — `run_council` — which yields SSE-shaped events as nodes execute.
"""

from graph.builder import build_council_graph, run_council
from graph.state import CouncilState, GraphEvent

__all__ = ["build_council_graph", "run_council", "CouncilState", "GraphEvent"]
