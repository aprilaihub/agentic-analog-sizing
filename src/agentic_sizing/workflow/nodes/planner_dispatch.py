from __future__ import annotations

from ...core.models import PlannerTask, make_iteration_record
from ...iteration import run_iterative_planner
from ...iteration.context import compute_weighted_violations, resolve_case_name
from ..routing import find_unsatisfied_perfs
from ..state import AgenticSizingState


def planner_dispatch(state: AgenticSizingState) -> AgenticSizingState:
    case_name = resolve_case_name(state.get("case_name", ""), state.get("netlist_path", ""))
    anchor_status_for_prompt = _build_recovery_anchor_status(state)

    planner_result = run_iterative_planner(
        case_name=case_name,
        simulation_record_path=state.get("simulation_record_path", ""),
        current_predicted_perfs=state.get("predicted_perfs") or state.get("current_perfs"),
        current_operation_region_summary=state.get("operation_region_summary"),
        enable_kb_input=bool(state.get("enable_kb_input", True)),
        enable_heuristics=bool(state.get("enable_heuristics", True)),
        anchor_status=anchor_status_for_prompt,
        history=list(state.get("history", [])),
        objective_when_feasible=bool(state.get("continue_after_specs", False)),
        # current_perf_hint=state.get("current_perf", ""),
        provider="openai",
        model="gpt-5.2",
        reasoning_effort="high",
        max_retries=2,
        temperature=0.5,
        llm_client=state.get("llm_client"),
    )

    state_action = str(planner_result.get("state_action", "continue_current"))
    recovery_result = _apply_recovery_action(state, state_action)
    selected_role_name = planner_result["selected_role_name"]
    target_metric = planner_result["target_metric"]

    roles = state.get("functional_roles", [])
    chosen_role = next((role for role in roles if role.role_name == selected_role_name), None)

    if chosen_role is None:
        raise RuntimeError(
            f"Planner selected role '{selected_role_name}' not found in state.functional_roles"
        )

    planner_task = PlannerTask(
        target_metric=target_metric,
        selected_role_name=selected_role_name,
        worker_instruction=planner_result["worker_instruction"],
        selection_rationale=planner_result["selection_rationale"],
        focus_kb_evidence=list(planner_result["focus_kb_evidence"]),
        unsatisfied_metrics=list(planner_result.get("unsatisfied_metrics", [])),
    )

    history = list(state.get("history", []))
    history.append(
        make_iteration_record(
            iteration=state.get("iteration", 0),
            node="planner_dispatch",
            decision="llm_dispatch_task_to_worker",
            details={
                "case_name": case_name,
                "state_action": state_action,
                "state_action_applied": recovery_result["applied"],
                "recovery_rationale": planner_result.get("recovery_rationale", ""),
                "target_metric": target_metric,
                "selected_role_name": selected_role_name,
                "selected_role_id": chosen_role.role_id,
                "worker_instruction": planner_task.worker_instruction,
            },
        )
    )

    return {
        "case_name": case_name,
        **recovery_result["updates"],
        "current_perf": target_metric,
        "current_role": chosen_role,
        "planner_task": planner_task,
        "unsatisfied_perfs": recovery_result["unsatisfied_perfs"]
        if recovery_result["unsatisfied_perfs"] is not None
        else list(planner_result.get("unsatisfied_metrics", state.get("unsatisfied_perfs", []))),
        "history": history,
    }


def _build_recovery_anchor_status(state: AgenticSizingState) -> dict:
    base = dict(state.get("last_anchor_status", {}))
    current_perfs = dict(state.get("predicted_perfs") or state.get("current_perfs") or {})
    best_known_perfs = dict(state.get("best_known_perfs", {}))
    current_score = _weighted_violation(current_perfs, state)
    best_score = _weighted_violation(best_known_perfs, state)
    current_state_score = _state_score(current_perfs, state)
    best_state_score = _state_score(best_known_perfs, state)
    revert_allowed = bool(best_known_perfs) and current_state_score > best_state_score
    base.update(
        {
            "current_weighted_violation": current_score,
            "best_known_weighted_violation": best_score,
            "current_objective_sort": current_state_score[1],
            "best_known_objective_sort": best_state_score[1],
            "revert_guard_passed": revert_allowed,
            "allowed_recovery_actions": ["continue_current", "revert_to_best_known"]
            if revert_allowed
            else ["continue_current"],
        }
    )
    return base


def _apply_recovery_action(state: AgenticSizingState, state_action: str) -> dict:
    if state_action != "revert_to_best_known":
        return {"applied": False, "updates": {}, "unsatisfied_perfs": None}

    best_known_design_vars = dict(state.get("best_known_design_vars", {}))
    best_known_perfs = dict(state.get("best_known_perfs", {}))
    current_perfs = dict(state.get("predicted_perfs") or state.get("current_perfs") or {})
    if not best_known_design_vars or not best_known_perfs:
        return {"applied": False, "updates": {}, "unsatisfied_perfs": None}

    current_score = _weighted_violation(current_perfs, state)
    best_score = _weighted_violation(best_known_perfs, state)
    current_state_score = _state_score(current_perfs, state)
    best_state_score = _state_score(best_known_perfs, state)
    if current_state_score <= best_state_score:
        return {"applied": False, "updates": {}, "unsatisfied_perfs": None}

    unsatisfied = find_unsatisfied_perfs(state.get("specs", []), best_known_perfs)
    anchor_status = {
        "action": "llm_reverted_to_best_known",
        "best_known_iteration": int(state.get("best_known_iteration", 0) or 0),
        "latest_record_iter": int(state.get("iteration", 0) or 0),
        "reverted": True,
        "current_weighted_violation": current_score,
        "best_known_weighted_violation": best_score,
        "current_objective_sort": current_state_score[1],
        "best_known_objective_sort": best_state_score[1],
        "message": "Planner requested revert_to_best_known and the deterministic guard allowed it.",
    }
    return {
        "applied": True,
        "updates": {
            "current_design_vars": best_known_design_vars,
            "current_perfs": best_known_perfs,
            "predicted_perfs": best_known_perfs,
            "last_anchor_status": anchor_status,
        },
        "unsatisfied_perfs": unsatisfied,
    }


def _weighted_violation(perfs: dict, state: AgenticSizingState) -> float:
    outputs_spec = {
        spec.name: [float(spec.target), str(spec.relation), float(spec.weight)]
        for spec in state.get("specs", [])
        if hasattr(spec, "name") and hasattr(spec, "target") and hasattr(spec, "relation")
    }
    return compute_weighted_violations(perfs, outputs_spec)


def _state_score(perfs: dict, state: AgenticSizingState) -> tuple[float, float]:
    return (
        _weighted_violation(perfs, state),
        _objective_sort_value(
            perfs,
            metric=str(state.get("objective_metric", "")),
            sense=str(state.get("objective_sense", "min")),
        ),
    )


def _objective_sort_value(perfs: dict, *, metric: str, sense: str) -> float:
    if not metric or metric not in perfs:
        return 0.0
    value = float(perfs[metric])
    return -value if sense == "max" else value
