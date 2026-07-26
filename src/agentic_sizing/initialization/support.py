from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence

from ..core.models import FunctionalRole, SpecConstraint
from ..core.operation_region import (
    extract_response_order as extract_all_response_order,
)
from ..core.operation_region import (
    filter_core_performance_metrics,
)
from ..llm.contract import StructuredLLMClient
from ..workflow.state import PROJECT_ROOT
from .errors import InitializePipelineError
from .initialize_worker import run_initialize_worker

SYNTHETIC_CONTROL_ROLE = "Testbench and bias controls"


def infer_case_name(netlist_path: str) -> str:
    candidate = Path(netlist_path).expanduser()
    name = candidate.stem if candidate.suffix else candidate.name
    name = name.strip()
    if not name:
        raise InitializePipelineError(f"Cannot infer case name from netlist path: {netlist_path}")
    return name


def build_spec_constraints(design_specs_json: Any) -> List[SpecConstraint]:
    if not isinstance(design_specs_json, dict):
        raise InitializePipelineError("design specs must be a JSON object")
    perf_specs = design_specs_json.get("performance_specs")
    if not isinstance(perf_specs, list) or not perf_specs:
        raise InitializePipelineError("design_specs.performance_specs must be a non-empty array")

    specs: List[SpecConstraint] = []
    for idx, item in enumerate(perf_specs):
        if not isinstance(item, dict):
            raise InitializePipelineError(
                f"design_specs.performance_specs[{idx}] must be an object"
            )

        name = item.get("name")
        method = item.get("method")
        threshold = item.get("threshold")
        weight = item.get("weight", 1.0)

        if not isinstance(name, str) or not name.strip():
            raise InitializePipelineError(f"design_specs.performance_specs[{idx}].name invalid")
        if method not in {"min", "max", "target"}:
            raise InitializePipelineError(f"design_specs.performance_specs[{idx}].method invalid")
        if not isinstance(threshold, (int, float)):
            raise InitializePipelineError(
                f"design_specs.performance_specs[{idx}].threshold invalid"
            )
        if not isinstance(weight, (int, float)):
            raise InitializePipelineError(f"design_specs.performance_specs[{idx}].weight invalid")

        specs.append(
            SpecConstraint(
                name=name,
                target=float(threshold),
                relation=method,
                weight=float(weight),
            )
        )

    return specs


def build_functional_roles(
    tagging_json: Any,
    kb_role_perf_json: Any,
    fallback_metrics: Iterable[str],
    settings_json: Mapping[str, Any] | None = None,
) -> List[FunctionalRole]:
    if not isinstance(tagging_json, dict):
        raise InitializePipelineError("tagging must be a JSON object")

    stage1 = tagging_json.get("stage1")
    stage2 = tagging_json.get("stage2")
    if not isinstance(stage1, dict) or not isinstance(stage2, dict):
        raise InitializePipelineError("tagging.stage1/stage2 must be JSON objects")

    stage1_roles = stage1.get("functional_roles")
    stage2_roles = stage2.get("roles")
    if not isinstance(stage1_roles, list) or not isinstance(stage2_roles, list):
        raise InitializePipelineError(
            "tagging.stage1.functional_roles and tagging.stage2.roles must be arrays"
        )

    role_to_metrics = _extract_role_perf_mapping(kb_role_perf_json)
    fallback = list(
        dict.fromkeys(
            metric for metric in fallback_metrics if isinstance(metric, str) and metric.strip()
        )
    )

    roles: List[FunctionalRole] = []
    for role in stage1_roles:
        if not isinstance(role, dict):
            continue
        role_name = role.get("name")
        if not isinstance(role_name, str) or not role_name.strip():
            continue

        role_stage2 = _find_stage2_role(stage2_roles, role_name)
        subblocks = _extract_subblocks(role_stage2)
        design_vars = _extract_role_design_variables(role_stage2)
        affectable_perfs = role_to_metrics.get(role_name) or fallback

        roles.append(
            FunctionalRole(
                role_id=_slugify_role(role_name),
                role_name=role_name,
                subblocks=subblocks,
                design_variables=design_vars,
                affectable_perfs=affectable_perfs,
            )
        )

    unowned_vars = _extract_unowned_design_variables(tagging_json, settings_json or {})
    if unowned_vars:
        roles.append(
            FunctionalRole(
                role_id=_slugify_role(SYNTHETIC_CONTROL_ROLE),
                role_name=SYNTHETIC_CONTROL_ROLE,
                subblocks=["testbench_and_bias_controls"],
                design_variables=unowned_vars,
                affectable_perfs=fallback,
            )
        )

    if not roles:
        raise InitializePipelineError("No functional roles were built from tagging output")
    return roles


def _resolve_case_paths(case_name: str) -> Dict[str, Path]:
    return {
        "settings_path": PROJECT_ROOT / "input" / "kb" / f"{case_name}_settings.json",
        "design_specs_path": PROJECT_ROOT / "output" / "kb" / f"{case_name}_design_specs.json",
        "tagging_path": PROJECT_ROOT / "output" / "tagging" / f"{case_name}.tagging.json",
        "kb_perf_tradeoff_path": PROJECT_ROOT
        / "output"
        / "kb"
        / f"{case_name}_kb_perf_tradeoff.json",
        "kb_role_perf_path": PROJECT_ROOT / "output" / "kb" / f"{case_name}_kb_role_perf.json",
        "kb_substruct_param_perf_path": PROJECT_ROOT
        / "output"
        / "kb"
        / f"{case_name}_kb_substruct_param_perf.json",
    }


def _normalize_assignments(
    worker_result: Mapping[str, Any],
    *,
    settings_json: Mapping[str, Any],
) -> Dict[str, float]:
    des_vars = settings_json.get("des_vars")
    if not isinstance(des_vars, dict):
        raise InitializePipelineError("settings.des_vars must be a JSON object")

    updates: Dict[str, float] = {}
    assignments = worker_result.get("assignments")
    if not isinstance(assignments, list):
        raise InitializePipelineError("worker_result.assignments must be an array")

    for item in assignments:
        if not isinstance(item, dict):
            raise InitializePipelineError("worker assignment item must be object")
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or name not in des_vars:
            raise InitializePipelineError(f"worker assignment contains unknown variable: {name}")
        if not isinstance(value, (int, float)):
            raise InitializePipelineError(
                f"worker assignment value must be numeric for variable: {name}"
            )

        var_def = des_vars[name]
        if not isinstance(var_def, list) or len(var_def) not in {2, 3}:
            raise InitializePipelineError(
                f"settings.des_vars.{name} must be [min,max] or [min,max,is_int]"
            )

        lower = float(var_def[0])
        upper = float(var_def[1])
        if value < lower or value > upper:
            raise InitializePipelineError(
                f"worker assignment out-of-range for {name}: {value} not in [{lower}, {upper}]"
            )

        is_int = bool(var_def[2]) if len(var_def) == 3 else False
        normalized_value = float(int(round(value))) if is_int else float(value)
        updates[name] = normalized_value

    return updates


def _build_llm_initial_candidates(
    *,
    role_plan: Sequence[Mapping[str, Any]],
    settings_file: Path,
    tagging_file: Path,
    design_specs_file: Path,
    kb_substruct_param_perf_file: Path,
    enable_kb_input: bool,
    enable_heuristics: bool,
    settings_json: Mapping[str, Any],
    design_var_order: Sequence[str],
    sample_count: int,
    provider: str,
    model: str,
    reasoning_effort: Optional[Literal["low", "medium", "high"]],
    max_retries: int,
    temperature: float,
    api_key: str | None,
    llm_client: StructuredLLMClient | None,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    previous_design_context: List[Dict[str, Any]] = []
    for sample_idx in range(sample_count):
        assignment_state: Dict[str, float] = {}
        worker_conversation: List[Dict[str, Any]] = []
        for role_item in role_plan:
            worker_result = run_initialize_worker(
                role_name=str(role_item["role_name"]),
                worker_instruction=_initial_sample_worker_instruction(
                    str(role_item["worker_instruction"]),
                    sample_idx=sample_idx,
                    sample_count=sample_count,
                ),
                settings_path=str(settings_file),
                tagging_path=str(tagging_file),
                design_specs_path=str(design_specs_file),
                kb_substruct_param_perf_path=str(kb_substruct_param_perf_file),
                prior_context=previous_design_context + worker_conversation,
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

            normalized_assignments = _normalize_assignments(
                worker_result,
                settings_json=settings_json,
            )
            for name, value in normalized_assignments.items():
                assignment_state[name] = value

            worker_conversation.append(
                {
                    "role_name": worker_result["role_name"],
                    "assignments": worker_result["assignments"],
                    "rationale": worker_result["rationale"],
                }
            )

        missing = [name for name in design_var_order if name not in assignment_state]
        if missing:
            raise InitializePipelineError(
                f"initialize assignments do not cover all design variables. missing={missing}"
            )

        parameters = [float(assignment_state[name]) for name in design_var_order]
        candidate = {
            "sample_index": sample_idx,
            "assignments": {name: float(assignment_state[name]) for name in design_var_order},
            "parameters": parameters,
            "worker_conversation": worker_conversation,
        }
        candidates.append(candidate)
        previous_design_context.append(
            {
                "kind": "previous_initial_design_candidate",
                "sample_index": sample_idx,
                "assignments": candidate["assignments"],
            }
        )
    return candidates


def _initial_sample_worker_instruction(
    base_instruction: str, *, sample_idx: int, sample_count: int
) -> str:
    if sample_count <= 1:
        return base_instruction
    return (
        f"{base_instruction}\n\n"
        f"You are proposing initial design candidate {sample_idx + 1} of {sample_count}. "
        "Return a complete role-local assignment for this candidate. Make this candidate "
        "materially distinct from earlier initial design candidates in prior_context while "
        "remaining physically plausible and inside all bounds."
    )


def _select_initial_record(
    *,
    initial_records: Sequence[Mapping[str, Any]],
    settings_json: Mapping[str, Any],
    perf_order: Sequence[str],
) -> Mapping[str, Any]:
    if not initial_records:
        raise InitializePipelineError("initial sampling produced no simulation records")

    outputs_spec = settings_json.get("outputs", {})
    objective = settings_json.get("objective", {})
    objective_metric = objective.get("name") if isinstance(objective, Mapping) else None
    objective_sense = objective.get("minormax") if isinstance(objective, Mapping) else None

    ranking = []
    for fallback_idx, item in enumerate(initial_records):
        performance = item.get("performance")
        if not isinstance(performance, Sequence) or isinstance(performance, (str, bytes)):
            raise InitializePipelineError("initial record performance must be a sequence")
        perf_map = {
            str(metric): float(performance[idx])
            for idx, metric in enumerate(perf_order)
            if idx < len(performance)
        }
        weighted_violation = _weighted_violation(perf_map, outputs_spec)
        objective_value = _objective_sort_value(
            perf_map=perf_map,
            objective_metric=objective_metric,
            objective_sense=objective_sense,
        )
        ranking.append((weighted_violation, objective_value, fallback_idx, item))

    ranking.sort(key=lambda row: (row[0], row[1], row[2]))
    return ranking[0][3]


def _weighted_violation(perfs: Mapping[str, float], outputs_spec: Any) -> float:
    if not isinstance(outputs_spec, Mapping):
        return 0.0

    total = 0.0
    for name, spec in outputs_spec.items():
        if name not in perfs:
            continue
        if not isinstance(spec, Sequence) or isinstance(spec, (str, bytes)) or len(spec) < 2:
            continue
        threshold = spec[0]
        method = spec[1]
        weight = spec[2] if len(spec) >= 3 else 1.0
        if not isinstance(threshold, (int, float)) or not isinstance(method, str):
            continue
        if not isinstance(weight, (int, float)):
            weight = 1.0

        value = float(perfs[name])
        if method == "min":
            total += max(float(threshold) - value, 0.0) * float(weight)
        elif method == "max":
            total += max(value - float(threshold), 0.0) * float(weight)
        elif method == "target":
            total += max(value - float(threshold), 0.0) * float(weight)
    return float(total)


def _objective_sort_value(
    *,
    perf_map: Mapping[str, float],
    objective_metric: Any,
    objective_sense: Any,
) -> float:
    if not isinstance(objective_metric, str) or objective_metric not in perf_map:
        return 0.0
    value = float(perf_map[objective_metric])
    if objective_sense == "max":
        return -value
    return value


def _extract_tagged_design_variables(tagging_json: Any) -> List[str]:
    if not isinstance(tagging_json, dict):
        return []
    stage2 = tagging_json.get("stage2")
    if not isinstance(stage2, dict):
        return []
    roles = stage2.get("roles")
    if not isinstance(roles, list):
        return []

    variables: List[str] = []
    seen: set[str] = set()
    for role in roles:
        if not isinstance(role, dict):
            continue
        substructures = role.get("substructures")
        if not isinstance(substructures, list):
            continue
        for sub in substructures:
            if not isinstance(sub, dict):
                continue
            vars_list = sub.get("variables")
            if not isinstance(vars_list, list):
                continue
            for item in vars_list:
                if not isinstance(item, dict):
                    continue
                design_variables = item.get("design_variables")
                if not isinstance(design_variables, list):
                    continue
                for name in design_variables:
                    if isinstance(name, str) and name.strip() and name not in seen:
                        seen.add(name)
                        variables.append(name)
    return variables


def _extract_unowned_design_variables(
    tagging_json: Any,
    settings_json: Mapping[str, Any],
) -> List[str]:
    des_vars = settings_json.get("des_vars")
    if not isinstance(des_vars, dict):
        return []
    tagged = set(_extract_tagged_design_variables(tagging_json))
    return [
        name
        for name in des_vars.keys()
        if isinstance(name, str) and name.strip() and name not in tagged
    ]


def _extract_design_var_order(settings_json: Mapping[str, Any]) -> List[str]:
    des_vars = settings_json.get("des_vars")
    if not isinstance(des_vars, dict) or not des_vars:
        raise InitializePipelineError("settings.des_vars must be a non-empty JSON object")
    return [name for name in des_vars.keys() if isinstance(name, str) and name.strip()]


def _extract_perf_order(settings_json: Mapping[str, Any]) -> List[str]:
    response_order = extract_all_response_order(settings_json)
    if not response_order:
        raise InitializePipelineError("settings.responses.assembler must be a non-empty JSON array")
    return filter_core_performance_metrics(response_order)


def _extract_role_perf_mapping(kb_role_perf_json: Any) -> Dict[str, List[str]]:
    if not isinstance(kb_role_perf_json, dict):
        return {}
    facts = kb_role_perf_json.get("facts")
    if not isinstance(facts, list):
        return {}

    mapping: Dict[str, List[str]] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        role = fact.get("functional_role")
        metric = fact.get("metric")
        if not isinstance(role, str) or not role.strip():
            continue
        if not isinstance(metric, str) or not metric.strip():
            continue
        bucket = mapping.setdefault(role, [])
        if metric not in bucket:
            bucket.append(metric)
    return mapping


def _find_stage2_role(stage2_roles: Sequence[Any], role_name: str) -> Mapping[str, Any]:
    for role in stage2_roles:
        if isinstance(role, dict) and role.get("name") == role_name:
            return role
    return {}


def _extract_subblocks(role_stage2: Mapping[str, Any]) -> List[str]:
    substructures = role_stage2.get("substructures")
    if not isinstance(substructures, list):
        return []

    subblocks: List[str] = []
    seen = set()
    for sub in substructures:
        if not isinstance(sub, dict):
            continue
        sub_type = sub.get("type")
        if isinstance(sub_type, str) and sub_type.strip() and sub_type not in seen:
            seen.add(sub_type)
            subblocks.append(sub_type)
    return subblocks


def _extract_role_design_variables(role_stage2: Mapping[str, Any]) -> List[str]:
    substructures = role_stage2.get("substructures")
    if not isinstance(substructures, list):
        return []

    result: List[str] = []
    seen = set()
    for sub in substructures:
        if not isinstance(sub, dict):
            continue
        variables = sub.get("variables")
        if not isinstance(variables, list):
            continue
        for variable in variables:
            if not isinstance(variable, dict):
                continue
            design_vars = variable.get("design_variables")
            if not isinstance(design_vars, list):
                continue
            for name in design_vars:
                if isinstance(name, str) and name.strip() and name not in seen:
                    seen.add(name)
                    result.append(name)
    return result


def _slugify_role(role_name: str) -> str:
    parts = [ch.lower() if ch.isalnum() else "_" for ch in role_name.strip()]
    role_id = "".join(parts)
    while "__" in role_id:
        role_id = role_id.replace("__", "_")
    return role_id.strip("_") or "role"


def _resolve_output_path(path: str) -> Path:
    return _resolve_path(path)


def _resolve_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    return (PROJECT_ROOT / candidate).resolve()


def _require_existing_file(path: Path, label: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{label} file not found: {path}")
    return path


def _load_json_file(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} file is not valid JSON: {path}") from exc
