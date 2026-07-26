from __future__ import annotations

from ...core.models import make_iteration_record
from ..routing import find_unsatisfied_perfs, runtime_limit_reached
from ..state import AgenticSizingState


def check_completion(state: AgenticSizingState) -> AgenticSizingState:
    perfs = state.get("predicted_perfs") or state.get("current_perfs", {})
    unsatisfied = find_unsatisfied_perfs(state.get("specs", []), perfs)
    planner_worker_iter = state.get("planner_worker_iter", 0)
    max_planner_worker_iter = state.get("max_planner_worker_iter", 2)

    termination_reason = state.get("termination_reason", "")
    feasible_objective_phase = bool(state.get("continue_after_specs", False)) and not unsatisfied
    if runtime_limit_reached(state):
        termination_reason = "time_limit_reached"
    elif state.get("iteration", 0) >= state.get("max_iter", 500):
        termination_reason = "max_iter_reached"
    elif (
        state.get("stagnation_count", 0) >= state.get("max_stagnation", 5)
        and not feasible_objective_phase
    ):
        termination_reason = "stagnation_reached"
    elif feasible_objective_phase:
        termination_reason = ""

    force_simulation_commit = (
        bool(state.get("force_simulation_commit", False))
        or (not unsatisfied)
        or (planner_worker_iter >= max_planner_worker_iter)
    )

    history = list(state.get("history", []))
    history.append(
        make_iteration_record(
            iteration=state.get("iteration", 0),
            node="check_completion",
            decision="evaluate_predicted_specs",
            details={
                "unsatisfied_perfs": unsatisfied,
                "planner_worker_iter": planner_worker_iter,
                "max_planner_worker_iter": max_planner_worker_iter,
                "force_simulation_commit": force_simulation_commit,
                "feasible_objective_phase": feasible_objective_phase,
            },
        )
    )

    return {
        "unsatisfied_perfs": unsatisfied,
        "termination_reason": termination_reason,
        "force_simulation_commit": force_simulation_commit,
        "history": history,
    }
