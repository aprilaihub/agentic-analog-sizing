from __future__ import annotations

import time

from ...core.models import make_iteration_record
from ...initialization.pipeline import infer_case_name
from ...initialization.record_store import append_simulation_record
from ...kb.runtime_seed import prepare_runtime_kb_from_seed
from ...simulator import MockSimulationAdapter
from ..state import AgenticSizingState, resolve_agentic_path


def simulate_init(state: AgenticSizingState) -> AgenticSizingState:
    initialize_mode = state.get("initialize_mode", "real")
    simulation_backend = state.get("simulation_backend", "real")

    if initialize_mode == "real":
        from ...initialization.pipeline import run_initialize_pipeline

        init_result = run_initialize_pipeline(
            netlist_path=state.get("netlist_path", ""),
            simulation_record_path=state.get(
                "simulation_record_path", "output/simulation_record.json"
            ),
            enable_kb_input=bool(state.get("enable_kb_input", True)),
            enable_heuristics=bool(state.get("enable_heuristics", True)),
            simulation_backend=simulation_backend,
            initial_sample_count=int(state.get("initial_sample_count", 1) or 1),
        )

        current_perfs = init_result["initial_perfs"]
        current_design_vars = init_result["initial_design_vars"]
        history = list(state.get("history", []))
        history.append(
            make_iteration_record(
                iteration=init_result["record"]["iter"],
                node="simulate_init",
                decision="initialize_pipeline_complete",
                details={
                    "case_name": init_result["case_name"],
                    "simulation_backend": simulation_backend,
                    "record_iter": init_result["record"]["iter"],
                    "initial_sample_count": init_result.get("initial_sample_count", 1),
                    "selected_initial_sample_index": init_result.get(
                        "selected_initial_sample_index", 0
                    ),
                    "design_var_count": len(init_result["design_var_order"]),
                    "perf_count": len(init_result["perf_order"]),
                    "kb_seed": init_result.get("kb_seed_result", {}),
                },
            )
        )

        return {
            "case_name": init_result["case_name"],
            "current_design_vars": current_design_vars,
            "current_perfs": current_perfs,
            "operation_region_summary": dict(init_result.get("operation_region_summary", {})),
            "predicted_perfs": dict(current_perfs),
            "best_known_design_vars": dict(current_design_vars),
            "best_known_perfs": dict(current_perfs),
            "best_known_iteration": int(init_result["record"]["iter"]),
            "last_anchor_status": {
                "action": "initialized_anchor",
                "best_known_iteration": int(init_result["record"]["iter"]),
                "latest_record_iter": int(init_result["record"]["iter"]),
                "reverted": False,
                "message": "Initial simulated state established the best-known anchor.",
            },
            "objective_metric": str(
                init_result.get("objective_metric") or state.get("objective_metric", "")
            ),
            "objective_sense": str(
                init_result.get("objective_sense") or state.get("objective_sense", "min")
            ),
            "specs": init_result["specs"],
            "functional_roles": init_result["functional_roles"],
            "design_var_order": init_result["design_var_order"],
            "perf_order": init_result["perf_order"],
            "iteration": init_result["record"]["iter"],
            "simulation_record_path": init_result["simulation_record_path"],
            "planner_worker_iter": 0,
            "force_simulation_commit": False,
            "history": history,
        }

    case_name = str(state.get("case_name", "")).strip()
    if not case_name:
        case_name = infer_case_name(state.get("netlist_path", ""))
    kb_seed_result = prepare_runtime_kb_from_seed(
        case_name=case_name,
    )

    adapter = state.get("simulation_adapter") or MockSimulationAdapter(seed=2026)
    current_design_vars = dict(state.get("current_design_vars", {}))
    start_time = time.perf_counter()
    current_perfs = adapter.simulate(current_design_vars)
    simulation_cost_time_s = float(time.perf_counter() - start_time)
    design_var_order = list(state.get("design_var_order") or current_design_vars.keys())
    perf_order = list(state.get("perf_order") or current_perfs.keys())

    parameters = [float(current_design_vars[name]) for name in design_var_order]
    performance = [float(current_perfs[name]) for name in perf_order]
    record = append_simulation_record(
        state.get("simulation_record_path", resolve_agentic_path("output/simulation_record.json")),
        parameters=parameters,
        performance=performance,
        iteration=state.get("iteration", 0),
        cost_time_s=simulation_cost_time_s,
    )

    history = list(state.get("history", []))
    history.append(
        make_iteration_record(
            iteration=record["iter"],
            node="simulate_init",
            decision="initial_simulation_complete_mock",
            details={
                "perfs": current_perfs,
                "simulation_backend": "mock",
                "record_iter": record["iter"],
                "case_name": case_name,
                "kb_seed": kb_seed_result,
            },
        )
    )

    return {
        "current_design_vars": current_design_vars,
        "current_perfs": current_perfs,
        "operation_region_summary": {},
        "predicted_perfs": dict(current_perfs),
        "best_known_design_vars": dict(current_design_vars),
        "best_known_perfs": dict(current_perfs),
        "best_known_iteration": int(record["iter"]),
        "last_anchor_status": {
            "action": "initialized_anchor",
            "best_known_iteration": int(record["iter"]),
            "latest_record_iter": int(record["iter"]),
            "reverted": False,
            "message": "Initial simulated state established the best-known anchor.",
        },
        "objective_metric": state.get("objective_metric", "power"),
        "objective_sense": state.get("objective_sense", "min"),
        "iteration": record["iter"],
        "design_var_order": design_var_order,
        "perf_order": perf_order,
        "planner_worker_iter": 0,
        "force_simulation_commit": False,
        "case_name": case_name,
        "history": history,
    }
