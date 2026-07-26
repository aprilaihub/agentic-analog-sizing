from __future__ import annotations

from ...core.models import make_iteration_record
from ..routing import find_unsatisfied_perfs, runtime_limit_reached
from ..state import AgenticSizingState


def select_unsat_perf(state: AgenticSizingState) -> AgenticSizingState:
    perf_values = state.get("predicted_perfs") or state.get("current_perfs", {})
    unsatisfied = find_unsatisfied_perfs(state.get("specs", []), perf_values)

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
    elif not unsatisfied and not feasible_objective_phase:
        termination_reason = "all_specs_met"
    elif feasible_objective_phase:
        termination_reason = ""

    current_perf = unsatisfied[0] if unsatisfied else state.get("objective_metric", "")

    history = list(state.get("history", []))
    history.append(
        make_iteration_record(
            iteration=state.get("iteration", 0),
            node="select_unsat_perf",
            decision="select_next_perf",
            details={
                "current_perf": current_perf,
                "unsatisfied_perfs": unsatisfied,
                "feasible_objective_phase": feasible_objective_phase,
            },
        )
    )

    return {
        "unsatisfied_perfs": unsatisfied,
        "current_perf": current_perf,
        "termination_reason": termination_reason,
        "history": history,
    }
