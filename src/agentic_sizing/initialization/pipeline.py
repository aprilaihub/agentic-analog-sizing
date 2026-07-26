from __future__ import annotations

from typing import Any, Dict, List, Literal, Mapping, Optional

from ..kb.runtime_seed import prepare_runtime_kb_from_seed
from ..llm.contract import StructuredLLMClient
from ..specs.case_settings import materialize_case_settings_json
from ..specs.extract_design_specs import extract_design_specs_file
from .initialize_planner import run_initialize_planner
from .record_store import append_simulation_record
from .simulation import (
    simulate_performance_batch_vectors_with_regions,
    simulate_performance_vector,
    simulate_performance_vector_with_regions,
)
from .support import (
    _build_llm_initial_candidates,
    _extract_design_var_order,
    _extract_perf_order,
    _load_json_file,
    _require_existing_file,
    _resolve_case_paths,
    _resolve_output_path,
    _select_initial_record,
    build_functional_roles,
    build_spec_constraints,
    infer_case_name,
)

SYNTHETIC_CONTROL_ROLE = "Testbench and bias controls"

__all__ = [
    "build_functional_roles",
    "build_spec_constraints",
    "infer_case_name",
    "run_initialize_pipeline",
    "simulate_performance_batch_vectors_with_regions",
    "simulate_performance_vector",
    "simulate_performance_vector_with_regions",
]


def run_initialize_pipeline(
    netlist_path: str,
    simulation_record_path: str = "output/simulation_record.json",
    enable_kb_input: bool = True,
    enable_heuristics: bool = True,
    provider: str = "openai",
    model: str = "gpt-5.2",
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = "high",
    max_retries: int = 2,
    temperature: float = 0.5,
    api_key: str | None = None,
    llm_client: StructuredLLMClient | None = None,
    simulation_backend: Literal["real", "mock"] = "real",
    initial_sample_count: int = 1,
) -> Dict[str, Any]:
    case_name = infer_case_name(netlist_path)
    paths = _resolve_case_paths(case_name)
    kb_seed_result = prepare_runtime_kb_from_seed(
        case_name=case_name,
    )

    settings_file = _require_existing_file(
        materialize_case_settings_json(case_name, settings_path=paths["settings_path"]),
        "settings",
    )
    tagging_file = _require_existing_file(paths["tagging_path"], "tagging")
    kb_perf_tradeoff_file = (
        _require_existing_file(paths["kb_perf_tradeoff_path"], "kb perf tradeoff")
        if enable_kb_input
        else paths["kb_perf_tradeoff_path"]
    )
    kb_role_perf_file = (
        _require_existing_file(paths["kb_role_perf_path"], "kb role perf")
        if enable_kb_input
        else paths["kb_role_perf_path"]
    )
    kb_substruct_param_perf_file = (
        _require_existing_file(
            paths["kb_substruct_param_perf_path"],
            "kb substruct param perf",
        )
        if enable_kb_input
        else paths["kb_substruct_param_perf_path"]
    )

    extract_design_specs_file(
        input_settings_path=str(settings_file),
        output_path=str(paths["design_specs_path"]),
    )

    settings_json = _load_json_file(settings_file, "settings")
    design_specs_json = _load_json_file(paths["design_specs_path"], "design specs")
    tagging_json = _load_json_file(tagging_file, "tagging")
    kb_role_perf_json = (
        _load_json_file(kb_role_perf_file, "kb role perf") if enable_kb_input else {"facts": []}
    )

    planner_result = run_initialize_planner(
        settings_path=str(settings_file),
        tagging_path=str(tagging_file),
        kb_perf_tradeoff_path=str(kb_perf_tradeoff_file),
        kb_role_perf_path=str(kb_role_perf_file),
        design_specs_path=str(paths["design_specs_path"]),
        enable_kb_input=enable_kb_input,
        enable_heuristics=enable_heuristics,
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        max_retries=max_retries,
        temperature=temperature,
        api_key=api_key,
        llm_client=llm_client,
    )

    all_vars = list(_extract_design_var_order(settings_json))
    perf_order = _extract_perf_order(settings_json)
    initial_sample_count = max(1, int(initial_sample_count))

    initial_candidates = _build_llm_initial_candidates(
        role_plan=planner_result["role_execution_plan"],
        settings_file=settings_file,
        tagging_file=tagging_file,
        design_specs_file=paths["design_specs_path"],
        kb_substruct_param_perf_file=kb_substruct_param_perf_file,
        enable_kb_input=enable_kb_input,
        enable_heuristics=enable_heuristics,
        settings_json=settings_json,
        design_var_order=all_vars,
        sample_count=initial_sample_count,
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        max_retries=max_retries,
        temperature=temperature,
        api_key=api_key,
        llm_client=llm_client,
    )

    performance_batch, operation_region_summaries, simulation_cost_times = (
        simulate_performance_batch_vectors_with_regions(
            settings_path=str(settings_file),
            parameter_batch=[candidate["parameters"] for candidate in initial_candidates],
            perf_order=perf_order,
            simulation_backend=simulation_backend,
        )
    )

    simulation_record_resolved = _resolve_output_path(simulation_record_path)
    initial_records: List[Dict[str, Any]] = []
    for candidate, performance_values, operation_region_summary, simulation_cost_time_s in zip(
        initial_candidates,
        performance_batch,
        operation_region_summaries,
        simulation_cost_times,
    ):
        record = append_simulation_record(
            str(simulation_record_resolved),
            parameters=candidate["parameters"],
            performance=performance_values,
            cost_time_s=simulation_cost_time_s,
        )
        initial_records.append(
            {
                "sample_index": int(candidate["sample_index"]),
                "parameters": [float(value) for value in candidate["parameters"]],
                "performance": [float(value) for value in performance_values],
                "operation_region_summary": dict(operation_region_summary),
                "record": record,
                "worker_conversation": candidate["worker_conversation"],
            }
        )

    selected_initial = _select_initial_record(
        initial_records=initial_records,
        settings_json=settings_json,
        perf_order=perf_order,
    )
    selected_parameters = list(selected_initial["parameters"])
    selected_performance = list(selected_initial["performance"])
    record = selected_initial["record"]

    initial_perfs = {
        metric: float(selected_performance[idx]) for idx, metric in enumerate(perf_order)
    }
    selected_assignment_state = {
        name: float(selected_parameters[idx]) for idx, name in enumerate(all_vars)
    }

    functional_roles = build_functional_roles(
        tagging_json=tagging_json,
        kb_role_perf_json=kb_role_perf_json,
        fallback_metrics=set(perf_order),
        settings_json=settings_json,
    )

    specs = build_spec_constraints(design_specs_json)
    objective = (
        design_specs_json.get("objective", {}) if isinstance(design_specs_json, Mapping) else {}
    )

    return {
        "case_name": case_name,
        "design_specs_path": str(paths["design_specs_path"]),
        "resolved_paths": {key: str(value) for key, value in paths.items()},
        "initial_design_vars": selected_assignment_state,
        "initial_perfs": initial_perfs,
        "initial_samples": initial_records,
        "initial_sample_count": len(initial_records),
        "selected_initial_sample_index": int(selected_initial["sample_index"]),
        "operation_region_summary": dict(selected_initial.get("operation_region_summary", {})),
        "design_var_order": list(all_vars),
        "perf_order": list(perf_order),
        "functional_roles": functional_roles,
        "specs": specs,
        "objective_metric": objective.get("metric", ""),
        "objective_sense": objective.get("sense", ""),
        "record": record,
        "simulation_record_path": str(simulation_record_resolved),
        "kb_seed_result": kb_seed_result,
    }
