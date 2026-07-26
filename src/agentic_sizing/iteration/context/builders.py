from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from ...core.llm_metric_ranges import (
    annotate_design_specs_for_llm,
    annotate_metric_items_for_llm,
    build_llm_metric_ranges_from_outputs,
)
from ...initialization.pipeline import infer_case_name
from ...specs.case_settings import materialize_case_settings_json
from ...specs.extract_design_specs import extract_design_specs_file
from ...workflow.state import PROJECT_ROOT
from ..run_role_perf import get_run_role_perf_path
from .data import (
    _trim_role_substructures_for_prompt,
    evaluate_unsatisfied_metrics,
    extract_design_var_order,
    extract_perf_metrics_from_design_specs,
    extract_perf_order,
    extract_role_design_variables_from_substructures,
    extract_role_substructure_types,
    extract_role_substructures,
    extract_stage1_role_names,
    extract_variable_bounds,
    filter_perf_tradeoff_facts,
    filter_role_perf_facts,
    filter_substruct_param_perf_facts,
    load_json_file,
    load_latest_simulation_record,
    load_latest_simulation_records,
    load_optional_facts_file,
    map_parameter_vector,
    map_performance_vector,
    merge_fact_payloads,
    require_existing_file,
    select_improving_design_slices,
)
from .errors import IterativeSizingContextError
from .summaries import (
    _compress_latest_results,
    _filter_design_vars_for_role,
    _filter_improving_design_samples,
    _find_metric_spec,
    _map_simulation_records,
    _objective_metric_name,
    build_planner_local_summary,
    build_worker_local_summary,
)

SYNTHETIC_CONTROL_ROLE = "Testbench and bias controls"


def resolve_case_name(case_name: str | None, netlist_path: str) -> str:
    if case_name and case_name.strip():
        return case_name.strip()
    return infer_case_name(netlist_path)


def resolve_case_paths(case_name: str) -> Dict[str, Path]:
    kb_root = PROJECT_ROOT / "output" / "kb"

    def kb_view(suffix: str) -> Path:
        runtime = kb_root / f"{case_name}_kb_{suffix}.json"
        seed = kb_root / "pillars" / f"{case_name}_kb_{suffix}.json"
        return runtime if runtime.exists() else seed

    return {
        "settings_path": PROJECT_ROOT / "input" / "kb" / f"{case_name}_settings.json",
        "design_specs_path": PROJECT_ROOT / "output" / "kb" / f"{case_name}_design_specs.json",
        "tagging_path": PROJECT_ROOT / "output" / "tagging" / f"{case_name}.tagging.json",
        "kb_perf_tradeoff_path": kb_view("perf_tradeoff"),
        "kb_role_perf_path": kb_view("role_perf"),
        "kb_substruct_param_perf_path": kb_view("substruct_param_perf"),
    }


def ensure_design_specs(case_name: str, paths: Mapping[str, Path]) -> None:
    settings_path = require_existing_file(
        materialize_case_settings_json(case_name, settings_path=paths["settings_path"]),
        "settings",
    )
    design_specs_path = paths["design_specs_path"].resolve()
    if design_specs_path.exists():
        return
    extract_design_specs_file(str(settings_path), str(design_specs_path))


def build_planner_context(
    *,
    case_name: str,
    simulation_record_path: str,
    current_predicted_perfs: Mapping[str, float] | None,
    current_operation_region_summary: Mapping[str, Any] | None = None,
    enable_kb_input: bool = True,
    anchor_status: Mapping[str, Any] | None = None,
    history: Sequence[Any] | None = None,
    objective_when_feasible: bool = False,
) -> Dict[str, Any]:
    paths = resolve_case_paths(case_name)
    ensure_design_specs(case_name, paths)

    settings_json = load_json_file(
        require_existing_file(paths["settings_path"], "settings"), "settings"
    )
    design_specs_json = load_json_file(
        require_existing_file(paths["design_specs_path"], "design specs"), "design specs"
    )
    tagging_json = load_json_file(
        require_existing_file(paths["tagging_path"], "tagging"), "tagging"
    )
    if enable_kb_input:
        kb_role_perf_json = load_json_file(
            require_existing_file(paths["kb_role_perf_path"], "kb role perf"), "kb role perf"
        )
        kb_role_perf_json = merge_fact_payloads(
            kb_role_perf_json,
            load_optional_facts_file(get_run_role_perf_path(simulation_record_path)),
        )
        kb_perf_tradeoff_json = load_json_file(
            require_existing_file(paths["kb_perf_tradeoff_path"], "kb perf tradeoff"),
            "kb perf tradeoff",
        )
    else:
        kb_role_perf_json = {"facts": []}
        kb_perf_tradeoff_json = {"facts": []}

    latest_record = load_latest_simulation_record(simulation_record_path)
    recent_records = load_latest_simulation_records(simulation_record_path, k=8)
    design_var_order = extract_design_var_order(settings_json)
    perf_order = extract_perf_order(settings_json)
    recent_record_views = _map_simulation_records(recent_records, design_var_order, perf_order)
    latest_records = recent_record_views[-5:]

    latest_perfs = map_performance_vector(latest_record["performance"], perf_order)

    working_perfs = dict(latest_perfs)
    if current_predicted_perfs:
        for metric, value in current_predicted_perfs.items():
            if isinstance(metric, str) and isinstance(value, (int, float)):
                working_perfs[metric] = float(value)

    unsatisfied_metrics = evaluate_unsatisfied_metrics(working_perfs, design_specs_json)
    unsatisfied_metrics = annotate_metric_items_for_llm(
        unsatisfied_metrics,
        settings_json.get("outputs", {}),
    )
    if objective_when_feasible and not unsatisfied_metrics:
        objective_metric = _objective_metric_name(design_specs_json)
        if objective_metric:
            objective_spec = _find_metric_spec(objective_metric, design_specs_json)
            current_value = working_perfs.get(objective_metric)
            objective = (
                design_specs_json.get("objective") if isinstance(design_specs_json, Mapping) else {}
            )
            objective_sense = objective.get("sense") if isinstance(objective, Mapping) else "min"
            unsatisfied_metrics = [
                {
                    "name": objective_metric,
                    "index": int(objective_spec.get("index", 0)) if objective_spec else 0,
                    "method": f"objective_{objective_sense}",
                    "threshold": float(objective_spec.get("threshold", 0.0))
                    if objective_spec
                    else 0.0,
                    "current": float(current_value)
                    if isinstance(current_value, (int, float))
                    else None,
                    "gap": 0.0,
                    "objective_phase": True,
                }
            ]
    unsatisfied_names = [item["name"] for item in unsatisfied_metrics]

    allowed_roles = extract_stage1_role_names(tagging_json, settings_json)
    role_perf_facts = filter_role_perf_facts(kb_role_perf_json, unsatisfied_names)
    perf_tradeoff_facts = filter_perf_tradeoff_facts(kb_perf_tradeoff_json, unsatisfied_names)
    recent_role_metric_selections = summarize_recent_planner_selections(history or [], limit=5)

    planner_local_summary = build_planner_local_summary(
        working_performances=working_perfs,
        unsatisfied_metrics=unsatisfied_metrics,
        recent_records=recent_record_views,
        recent_role_metric_selections=recent_role_metric_selections,
        role_perf_facts=role_perf_facts,
        perf_tradeoff_facts=perf_tradeoff_facts,
        outputs_spec=settings_json.get("outputs", {}),
        anchor_status=anchor_status,
    )

    return {
        "case_name": case_name,
        "paths": {key: str(value.resolve()) for key, value in paths.items()},
        "settings": {
            "design_var_order": design_var_order,
            "perf_order": perf_order,
            "llm_metric_ranges": build_llm_metric_ranges_from_outputs(
                settings_json.get("outputs", {})
            ),
        },
        "latest_record": latest_records,
        "working_performances": working_perfs,
        "unsatisfied_metrics": unsatisfied_metrics,
        "allowed_roles": sorted(allowed_roles),
        "recent_role_metric_selections": recent_role_metric_selections,
        "role_perf_facts": role_perf_facts,
        "perf_tradeoff_facts": perf_tradeoff_facts,
        "planner_local_summary": planner_local_summary,
    }


def summarize_recent_planner_selections(
    history: Sequence[Any],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    normalized = [_history_item_to_dict(item) for item in history]
    normalized = [item for item in normalized if item]

    planner_indices = [
        idx
        for idx, item in enumerate(normalized)
        if item.get("node") == "planner_dispatch"
        and item.get("decision") == "llm_dispatch_task_to_worker"
    ]

    summaries: List[Dict[str, Any]] = []
    for start_idx in planner_indices:
        item = normalized[start_idx]
        details = item.get("details") or {}
        summaries.append(
            {
                "target_metric": str(details.get("target_metric", "")),
                "selected_role_name": str(details.get("selected_role_name", "")),
            }
        )

    return list(reversed(summaries))[: max(0, limit)]


def _history_item_to_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {
        "iteration": getattr(item, "iteration", -1),
        "node": getattr(item, "node", ""),
        "decision": getattr(item, "decision", ""),
        "details": getattr(item, "details", {}) or {},
    }


def build_worker_context(
    *,
    case_name: str,
    role_name: str,
    target_metric: str,
    simulation_record_path: str,
    current_design_vars: Mapping[str, float] | None,
    current_predicted_perfs: Mapping[str, float] | None,
    current_operation_region_summary: Mapping[str, Any] | None = None,
    enable_kb_input: bool = True,
    anchor_status: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    paths = resolve_case_paths(case_name)
    ensure_design_specs(case_name, paths)

    settings_json = load_json_file(
        require_existing_file(paths["settings_path"], "settings"), "settings"
    )
    design_specs_json = load_json_file(
        require_existing_file(paths["design_specs_path"], "design specs"), "design specs"
    )
    tagging_json = load_json_file(
        require_existing_file(paths["tagging_path"], "tagging"), "tagging"
    )
    kb_substruct_param_perf_json = (
        load_json_file(
            require_existing_file(paths["kb_substruct_param_perf_path"], "kb substruct-param-perf"),
            "kb substruct-param-perf",
        )
        if enable_kb_input
        else {"facts": []}
    )

    latest_record = load_latest_simulation_record(simulation_record_path)
    recent_records = load_latest_simulation_records(simulation_record_path, k=20)
    design_var_order = extract_design_var_order(settings_json)
    perf_order = extract_perf_order(settings_json)
    recent_record_views = _map_simulation_records(recent_records, design_var_order, perf_order)

    latest_design = map_parameter_vector(latest_record["parameters"], design_var_order)
    latest_perfs = map_performance_vector(latest_record["performance"], perf_order)

    working_design = dict(latest_design)
    if current_design_vars:
        for name, value in current_design_vars.items():
            if isinstance(name, str) and isinstance(value, (int, float)):
                working_design[name] = float(value)

    working_perfs = dict(latest_perfs)
    if current_predicted_perfs:
        for name, value in current_predicted_perfs.items():
            if isinstance(name, str) and isinstance(value, (int, float)):
                working_perfs[name] = float(value)

    role_substructures = extract_role_substructures(tagging_json, role_name, settings_json)
    role_variables = extract_role_design_variables_from_substructures(role_substructures)
    if not role_variables:
        raise IterativeSizingContextError(
            f"No design variables extracted from tagging for role '{role_name}'"
        )
    role_substructure_types = extract_role_substructure_types(role_substructures)
    all_perf_metrics = extract_perf_metrics_from_design_specs(design_specs_json)
    role_kb_substruct_param_perf_json = filter_substruct_param_perf_facts(
        kb_substruct_param_perf_json,
        role_substructure_types,
        allowed_metrics=all_perf_metrics,
        role_variables=role_variables,
    )

    variable_bounds = extract_variable_bounds(settings_json, role_variables)

    if target_metric not in all_perf_metrics:
        raise IterativeSizingContextError(
            f"Target metric '{target_metric}' is not in design specs metrics: {all_perf_metrics}"
        )

    selected_improving = select_improving_design_slices(
        recent_records,
        design_var_order=design_var_order,
        perf_order=perf_order,
        outputs_spec=settings_json.get("outputs", {}),
        objective_metric=str(settings_json.get("objective", {}).get("name", "")),
        latest_k=5,
        best_k=5,
    )
    filtered_improving = _filter_improving_design_samples(
        selected_improving,
        role_variables=role_variables,
        target_metric=target_metric,
    )
    latest_results = _compress_latest_results(
        recent_record_views[-5:],
        role_variables=role_variables,
    )
    role_working_design = _filter_design_vars_for_role(working_design, role_variables)
    worker_local_summary = build_worker_local_summary(
        role_name=role_name,
        target_metric=target_metric,
        role_variables=role_variables,
        working_design=working_design,
        working_performances=working_perfs,
        recent_records=recent_record_views,
        design_specs_json=design_specs_json,
        outputs_spec=settings_json.get("outputs", {}),
        anchor_status=anchor_status,
    )

    prompt_design_specs_json = annotate_design_specs_for_llm(
        {
            "objective": design_specs_json.get("objective", {}),
            "performance_specs": sorted(
                design_specs_json.get("performance_specs", []),
                key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0,
            ),
        }
    )

    return {
        "case_name": case_name,
        "paths": {key: str(value.resolve()) for key, value in paths.items()},
        "target_metric": target_metric,
        "role_name": role_name,
        "design_var_order": design_var_order,
        "perf_order": perf_order,
        "working_design_full": {
            name: float(value)
            for name, value in working_design.items()
            if isinstance(name, str) and isinstance(value, (int, float))
        },
        "latest_record": {
            "iter": int(latest_record["iter"]),
            "design_vars": latest_design,
            "performances": latest_perfs,
        },
        "working_state": {
            "design_vars": role_working_design,
            "performances": working_perfs,
        },
        "role_substructures": _trim_role_substructures_for_prompt(role_substructures),
        "role_variables": role_variables,
        "variable_bounds": variable_bounds,
        "required_performance_metrics": all_perf_metrics,
        "design_specs": prompt_design_specs_json,
        "latest_results": latest_results,
        "improving_design_samples": filtered_improving,
        "kb_substruct_param_perf": role_kb_substruct_param_perf_json,
        "worker_local_summary": worker_local_summary,
    }
