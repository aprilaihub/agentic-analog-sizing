from __future__ import annotations

from .nodes import (
    apply_update,
    check_completion,
    load_input,
    planner_dispatch,
    select_unsat_perf,
    simulate_commit,
    simulate_init,
    terminate,
    worker_propose,
)
from .routing import route_after_check, route_after_select

# from asyncio import graph
from .state import AgenticSizingState

try:
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "langgraph is required to build the agentic sizing state machine. "
        "Install the project with `python -m pip install -e .`"
    ) from exc


def build_state_graph() -> StateGraph:
    graph = StateGraph(AgenticSizingState)

    graph.add_node("load_input", load_input)
    graph.add_node("simulate_init", simulate_init)
    graph.add_node("select_unsat_perf", select_unsat_perf)
    graph.add_node("planner_dispatch", planner_dispatch)
    graph.add_node("worker_propose", worker_propose)
    graph.add_node("apply_update", apply_update)
    graph.add_node("check_completion", check_completion)
    graph.add_node("simulate_commit", simulate_commit)
    graph.add_node("terminate", terminate)

    graph.add_edge(START, "load_input")
    graph.add_edge("load_input", "simulate_init")
    graph.add_edge("simulate_init", "select_unsat_perf")

    graph.add_conditional_edges(
        "select_unsat_perf",
        route_after_select,
        {
            "planner_dispatch": "planner_dispatch",
            "terminate": "terminate",
        },
    )

    graph.add_edge("planner_dispatch", "worker_propose")
    graph.add_edge("worker_propose", "apply_update")
    graph.add_edge("apply_update", "check_completion")

    graph.add_conditional_edges(
        "check_completion",
        route_after_check,
        {
            "simulate_commit": "simulate_commit",
            "select_unsat_perf": "select_unsat_perf",
            "terminate": "terminate",
        },
    )

    graph.add_edge("simulate_commit", "select_unsat_perf")
    graph.add_edge("terminate", END)

    return graph


def compile_graph():
    graph = build_state_graph().compile()
    # print(graph.get_graph().draw_mermaid())
    return graph
