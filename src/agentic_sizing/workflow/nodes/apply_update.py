from __future__ import annotations

from ...core.models import make_iteration_record
from ..routing import find_unsatisfied_perfs
from ..state import AgenticSizingState


def apply_update(state: AgenticSizingState) -> AgenticSizingState:
    proposal = state.get("worker_proposal")
    role = state.get("current_role")

    design_vars = dict(state.get("current_design_vars", {}))
    predicted_perfs = dict(state.get("predicted_perfs") or state.get("current_perfs", {}))
    allowed_vars = set(role.design_variables) if role else set()
    rejected_updates = {}

    if proposal:
        for var_name, new_value in proposal.updated_design_vars.items():
            if var_name in allowed_vars:
                design_vars[var_name] = float(new_value)
            else:
                rejected_updates[var_name] = new_value

        if proposal.predicted_performances:
            predicted_perfs = {
                perf_name: float(value)
                for perf_name, value in proposal.predicted_performances.items()
            }

    old_unsatisfied_count = len(state.get("unsatisfied_perfs", []))
    unsatisfied_after_update = find_unsatisfied_perfs(state.get("specs", []), predicted_perfs)
    feasible_objective_phase = (
        bool(state.get("continue_after_specs", False))
        and old_unsatisfied_count == 0
        and len(unsatisfied_after_update) == 0
    )

    improved = len(unsatisfied_after_update) < old_unsatisfied_count
    if feasible_objective_phase:
        new_stagnation = 0
    else:
        new_stagnation = 0 if improved else state.get("stagnation_count", 0) + 1

    planner_worker_iter = state.get("planner_worker_iter", 0) + 1
    history = list(state.get("history", []))
    history.append(
        make_iteration_record(
            iteration=state.get("iteration", 0),
            node="apply_update",
            decision="apply_worker_updates_with_scope_guard",
            details={
                "rejected_updates": rejected_updates,
                "old_unsatisfied_count": old_unsatisfied_count,
                "new_unsatisfied_count": len(unsatisfied_after_update),
                "improved": improved,
                "feasible_objective_phase": feasible_objective_phase,
                "planner_worker_iter": planner_worker_iter,
            },
        )
    )

    return {
        "current_design_vars": design_vars,
        "predicted_perfs": predicted_perfs,
        "unsatisfied_perfs": unsatisfied_after_update,
        "stagnation_count": new_stagnation,
        "planner_worker_iter": planner_worker_iter,
        "history": history,
    }
