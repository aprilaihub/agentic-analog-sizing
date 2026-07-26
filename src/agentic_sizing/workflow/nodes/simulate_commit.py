from __future__ import annotations

import time
from typing import Any

from ...core.models import make_iteration_record
from ...initialization.record_store import append_simulation_record
from ...iteration.context import compute_weighted_violations
from ...iteration.run_role_perf import update_run_role_perf_summary
from ...simulator import MockSimulationAdapter
from ...specs.case_settings import materialize_case_settings_json
from ..routing import find_unsatisfied_perfs
from ..state import AgenticSizingState, resolve_agentic_path


def simulate_commit(state: AgenticSizingState) -> AgenticSizingState:
    simulation_backend = state.get("simulation_backend", "real")
    initialize_mode = state.get("initialize_mode", "real")

    design_vars = dict(state.get("current_design_vars", {}))
    design_var_order = list(state.get("design_var_order", []))
    perf_order = list(state.get("perf_order", []))
    case_name = state.get("case_name", "")

    (
        simulated_perfs,
        perf_values,
        operation_region_summary,
        simulation_cost_time_s,
        case_name,
        simulation_backend,
        design_var_order,
        perf_order,
    ) = _simulate_design(
        state=state,
        design_vars=design_vars,
        design_var_order=design_var_order,
        perf_order=perf_order,
        case_name=case_name,
        simulation_backend=simulation_backend,
        initialize_mode=initialize_mode,
    )

    record = append_simulation_record(
        state.get("simulation_record_path", resolve_agentic_path("output/simulation_record.json")),
        parameters=[float(design_vars[name]) for name in design_var_order],
        performance=perf_values,
        iteration=state.get("iteration", 0),
        cost_time_s=simulation_cost_time_s,
    )

    unsatisfied = find_unsatisfied_perfs(state.get("specs", []), simulated_perfs)
    update_run_role_perf_summary(
        simulation_record_path=state.get(
            "simulation_record_path", resolve_agentic_path("output/simulation_record.json")
        ),
        role=state.get("current_role"),
        metric=str(state.get("current_perf", "")),
        before_perfs=dict(state.get("current_perfs", {})),
        after_perfs=simulated_perfs,
        specs=list(state.get("specs", [])),
        iteration=int(record["iter"]),
    )

    history = list(state.get("history", []))
    history.append(
        make_iteration_record(
            iteration=state.get("iteration", 0),
            node="simulate_commit",
            decision="simulation_commit",
            details={
                "case_name": case_name,
                "simulation_backend": simulation_backend,
                "record_path": state.get("simulation_record_path", ""),
                "record_iter": record["iter"],
                "simulated_perfs": simulated_perfs,
                "unsatisfied_perfs": unsatisfied,
            },
        )
    )

    return _finalize_simulated_selection(
        state=state,
        selected_design_vars=design_vars,
        selected_perfs=simulated_perfs,
        selected_operation_region_summary=operation_region_summary,
        selected_unsatisfied=unsatisfied,
        iteration=int(record["iter"]),
        case_name=case_name,
        design_var_order=design_var_order,
        perf_order=perf_order,
        history=history,
    )


def _simulate_design(
    *,
    state: AgenticSizingState,
    design_vars: dict[str, float],
    design_var_order: list[str],
    perf_order: list[str],
    case_name: str,
    simulation_backend: str,
    initialize_mode: str,
) -> tuple[dict[str, float], list[float], dict[str, Any], float, str, str, list[str], list[str]]:
    resolved_design_var_order = (
        list(design_var_order) if design_var_order else list(design_vars.keys())
    )

    if initialize_mode == "real" and resolved_design_var_order and perf_order:
        from ...initialization.pipeline import (
            infer_case_name,
            simulate_performance_vector_with_regions,
        )

        case_name = case_name or infer_case_name(state.get("netlist_path", ""))
        settings_path = str(
            materialize_case_settings_json(
                case_name,
                settings_path=resolve_agentic_path(f"input/kb/{case_name}_settings.json"),
            )
        )
        parameters = [float(design_vars[name]) for name in resolved_design_var_order]
        perf_values, operation_region_summary, simulation_cost_time_s = (
            simulate_performance_vector_with_regions(
                settings_path=settings_path,
                parameters=parameters,
                perf_order=perf_order,
                simulation_backend=simulation_backend,
            )
        )
        simulated_perfs = {metric: float(perf_values[idx]) for idx, metric in enumerate(perf_order)}
        return (
            simulated_perfs,
            [float(value) for value in perf_values],
            dict(operation_region_summary),
            simulation_cost_time_s,
            case_name,
            simulation_backend,
            resolved_design_var_order,
            list(perf_order),
        )

    if not case_name:
        case_name = "mock_case"
    adapter = state.get("simulation_adapter") or MockSimulationAdapter(
        seed=2026 + state.get("iteration", 0)
    )
    start_time = time.perf_counter()
    simulated_perfs = adapter.simulate(design_vars)
    simulation_cost_time_s = float(time.perf_counter() - start_time)
    resolved_perf_order = list(perf_order) if perf_order else list(simulated_perfs.keys())
    perf_values = [float(simulated_perfs[name]) for name in resolved_perf_order]
    return (
        simulated_perfs,
        perf_values,
        {},
        simulation_cost_time_s,
        case_name,
        "mock",
        resolved_design_var_order,
        resolved_perf_order,
    )


def _finalize_simulated_selection(
    *,
    state: AgenticSizingState,
    selected_design_vars: dict[str, float],
    selected_perfs: dict[str, float],
    selected_operation_region_summary: dict[str, Any],
    selected_unsatisfied: list[str],
    iteration: int,
    case_name: str,
    design_var_order: list[str],
    perf_order: list[str],
    history,
) -> AgenticSizingState:
    best_known_design_vars = dict(state.get("best_known_design_vars", {}))
    best_known_perfs = dict(state.get("best_known_perfs", {}))
    best_known_iteration = int(state.get("best_known_iteration", 0) or 0)

    candidate_score = _state_score(selected_perfs, state)
    anchor_score = _state_score(best_known_perfs, state)

    if _simulated_state_better(
        candidate_perfs=selected_perfs,
        incumbent_perfs=best_known_perfs,
        state=state,
    ):
        best_known_design_vars = dict(selected_design_vars)
        best_known_perfs = dict(selected_perfs)
        best_known_iteration = int(iteration)
        anchor_status = {
            "action": "updated_anchor",
            "best_known_iteration": best_known_iteration,
            "latest_record_iter": int(iteration),
            "reverted": False,
            "message": "Latest simulated commit became the new best-known anchor.",
        }
    else:
        anchor_status = {
            "action": "kept_diverse_commit",
            "best_known_iteration": best_known_iteration,
            "latest_record_iter": int(iteration),
            "reverted": False,
            "candidate_score": {
                "weighted_violation": candidate_score[0],
                "objective_sort": candidate_score[1],
            },
            "anchor_score": {
                "weighted_violation": anchor_score[0],
                "objective_sort": anchor_score[1],
            },
            "message": (
                "Latest simulated commit did not beat the anchor, but the live state kept "
                "the simulated candidate."
            ),
        }

    return {
        "current_design_vars": dict(selected_design_vars),
        "current_perfs": dict(selected_perfs),
        "operation_region_summary": dict(selected_operation_region_summary),
        "predicted_perfs": dict(selected_perfs),
        "best_known_design_vars": best_known_design_vars,
        "best_known_perfs": best_known_perfs,
        "best_known_iteration": best_known_iteration,
        "last_anchor_status": anchor_status,
        "unsatisfied_perfs": list(selected_unsatisfied),
        "iteration": int(iteration),
        "planner_worker_iter": 0,
        "force_simulation_commit": False,
        "case_name": case_name,
        "design_var_order": list(design_var_order),
        "perf_order": list(perf_order),
        "history": history,
    }


def _simulated_state_better(
    *,
    candidate_perfs: dict[str, float],
    incumbent_perfs: dict[str, float],
    state: AgenticSizingState,
) -> bool:
    if not incumbent_perfs:
        return True
    return _state_score(candidate_perfs, state) < _state_score(incumbent_perfs, state)


def _state_score(perfs: dict[str, float], state: AgenticSizingState) -> tuple[float, float]:
    return (
        _spec_score(perfs, state.get("specs", [])),
        _objective_sort_value(
            perfs,
            metric=str(state.get("objective_metric", "")),
            sense=str(state.get("objective_sense", "min")),
        ),
    )


def _spec_score(perfs: dict[str, float], specs) -> float:
    outputs_spec = {
        spec.name: [float(spec.target), str(spec.relation), float(spec.weight)]
        for spec in specs
        if hasattr(spec, "name") and hasattr(spec, "target") and hasattr(spec, "relation")
    }
    return compute_weighted_violations(perfs, outputs_spec)


def _objective_sort_value(perfs: dict[str, float], *, metric: str, sense: str) -> float:
    if not metric or metric not in perfs:
        return 0.0
    value = float(perfs[metric])
    return -value if sense == "max" else value
