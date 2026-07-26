from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ...core.metric_aliases import canonical_metric_name, normalize_metric_set
from ...core.operation_region import (
    extract_response_order as extract_all_response_order,
)
from ...core.operation_region import (
    filter_core_performance_metrics,
)
from ...initialization.record_store import load_simulation_records
from .errors import IterativeSizingContextError

SYNTHETIC_CONTROL_ROLE = "Testbench and bias controls"


def require_existing_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"{label} file not found: {resolved}")
    return resolved


def load_json_file(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IterativeSizingContextError(f"{label} is not valid JSON: {path}") from exc


def load_optional_facts_file(path: Path) -> Dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return {"facts": []}
    payload = load_json_file(resolved, "local role perf")
    if not isinstance(payload, dict):
        raise IterativeSizingContextError(f"local role perf must be a JSON object: {resolved}")
    facts = payload.get("facts", [])
    if not isinstance(facts, list):
        raise IterativeSizingContextError(f"local role perf facts must be a JSON array: {resolved}")
    return {"facts": [dict(fact) for fact in facts if isinstance(fact, dict)]}


def merge_fact_payloads(*payloads: Mapping[str, Any]) -> Dict[str, Any]:
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for payload in payloads:
        facts = payload.get("facts") if isinstance(payload, Mapping) else None
        if not isinstance(facts, list):
            continue
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            key = (
                str(fact.get("type", "")),
                str(fact.get("functional_role", "")),
                str(fact.get("metric", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(fact))
    return {"facts": merged}


def load_latest_simulation_record(simulation_record_path: str) -> Dict[str, Any]:
    records = load_simulation_records(simulation_record_path)
    if not records:
        raise IterativeSizingContextError(
            f"simulation record file is empty or missing: {Path(simulation_record_path).expanduser().resolve()}"
        )
    return records[-1]


def load_latest_simulation_records(simulation_record_path: str, k: int) -> List[Dict[str, Any]]:
    records = load_simulation_records(simulation_record_path)
    if not records:
        raise IterativeSizingContextError(
            f"simulation record file is empty or missing: {Path(simulation_record_path).expanduser().resolve()}"
        )
    return records[-max(1, int(k)) :]


def extract_design_var_order(settings_json: Any) -> List[str]:
    if not isinstance(settings_json, dict):
        raise IterativeSizingContextError("settings must be a JSON object")
    des_vars = settings_json.get("des_vars")
    if not isinstance(des_vars, dict) or not des_vars:
        raise IterativeSizingContextError("settings.des_vars must be a non-empty object")
    return [name for name in des_vars.keys() if isinstance(name, str) and name.strip()]


def extract_perf_order(settings_json: Any) -> List[str]:
    if not isinstance(settings_json, dict):
        raise IterativeSizingContextError("settings must be a JSON object")
    response_order = extract_all_response_order(settings_json)
    if not response_order:
        raise IterativeSizingContextError("settings.responses.assembler must be a non-empty array")
    return filter_core_performance_metrics(response_order)


def map_parameter_vector(
    parameters: Sequence[float], design_var_order: Sequence[str]
) -> Dict[str, float]:
    if len(parameters) != len(design_var_order):
        raise IterativeSizingContextError(
            f"parameter dimension mismatch: got {len(parameters)} vs expected {len(design_var_order)}"
        )
    return {name: float(parameters[idx]) for idx, name in enumerate(design_var_order)}


def map_performance_vector(
    performance: Sequence[float], perf_order: Sequence[str]
) -> Dict[str, float]:
    if len(performance) != len(perf_order):
        raise IterativeSizingContextError(
            f"performance dimension mismatch: got {len(performance)} vs expected {len(perf_order)}"
        )
    return {name: float(performance[idx]) for idx, name in enumerate(perf_order)}


def extract_stage1_role_names(tagging_json: Any, settings_json: Any | None = None) -> set[str]:
    if not isinstance(tagging_json, dict):
        raise IterativeSizingContextError("tagging must be a JSON object")
    stage1 = tagging_json.get("stage1")
    if not isinstance(stage1, dict):
        raise IterativeSizingContextError("tagging.stage1 must be a JSON object")
    roles = stage1.get("functional_roles")
    if not isinstance(roles, list) or not roles:
        raise IterativeSizingContextError(
            "tagging.stage1.functional_roles must be a non-empty array"
        )

    role_names = {
        role.get("name")
        for role in roles
        if isinstance(role, dict)
        and isinstance(role.get("name"), str)
        and role.get("name", "").strip()
    }
    role_names = {name for name in role_names if isinstance(name, str)}
    stage2_editable_roles = _extract_stage2_roles_with_design_variables(tagging_json)
    if stage2_editable_roles:
        role_names &= stage2_editable_roles
    elif _has_design_variables(settings_json):
        role_names = set()

    if _extract_unowned_design_variables(tagging_json, settings_json or {}):
        role_names.add(SYNTHETIC_CONTROL_ROLE)
    if not role_names:
        raise IterativeSizingContextError(
            "No valid role names found in tagging.stage1.functional_roles"
        )
    return role_names


def _has_design_variables(settings_json: Any | None) -> bool:
    des_vars = settings_json.get("des_vars") if isinstance(settings_json, dict) else None
    return isinstance(des_vars, dict) and any(
        isinstance(name, str) and name.strip() for name in des_vars.keys()
    )


def _extract_stage2_roles_with_design_variables(tagging_json: Any) -> set[str]:
    if not isinstance(tagging_json, dict):
        return set()
    stage2 = tagging_json.get("stage2")
    if not isinstance(stage2, dict):
        return set()
    roles = stage2.get("roles")
    if not isinstance(roles, list):
        return set()

    role_names: set[str] = set()
    for role in roles:
        if not isinstance(role, dict):
            continue
        role_name = role.get("name")
        if not isinstance(role_name, str) or not role_name.strip():
            continue
        if extract_role_design_variables_from_substructures(
            role.get("substructures") if isinstance(role.get("substructures"), list) else []
        ):
            role_names.add(role_name)
    return role_names


def evaluate_unsatisfied_metrics(
    perf_values: Mapping[str, float], design_specs_json: Any
) -> List[Dict[str, Any]]:
    perf_specs = extract_performance_specs(design_specs_json)
    objective = (
        design_specs_json.get("objective") if isinstance(design_specs_json, Mapping) else None
    )
    objective_metric = objective.get("metric") if isinstance(objective, Mapping) else None
    unsatisfied: List[Dict[str, Any]] = []

    for spec in perf_specs:
        name = str(spec["name"])
        method = str(spec["method"])
        threshold = float(spec["threshold"])
        index = int(spec["index"])

        if name not in perf_values:
            unsatisfied.append(
                {
                    "name": name,
                    "index": index,
                    "method": method,
                    "threshold": threshold,
                    "current": None,
                    "gap": None,
                }
            )
            continue

        current = float(perf_values[name])
        if method == "min":
            is_ok = current >= threshold
            gap = max(0.0, threshold - current)
        elif method == "max":
            is_ok = current <= threshold
            gap = max(0.0, current - threshold)
        else:
            tolerance = max(abs(threshold) * 0.01, 1e-6)
            is_ok = (current - threshold) <= tolerance
            gap = max(current - threshold, 0)

        if not is_ok:
            unsatisfied.append(
                {
                    "name": name,
                    "index": index,
                    "method": method,
                    "threshold": threshold,
                    "current": current,
                    "gap": float(gap),
                }
            )

    unsatisfied.sort(key=lambda item: int(item["index"]))
    non_objective_unsatisfied = [
        item
        for item in unsatisfied
        if not (isinstance(objective_metric, str) and item["name"] == objective_metric)
    ]
    return non_objective_unsatisfied or unsatisfied


def extract_performance_specs(design_specs_json: Any) -> List[Dict[str, Any]]:
    if not isinstance(design_specs_json, dict):
        raise IterativeSizingContextError("design specs must be a JSON object")
    perf_specs = design_specs_json.get("performance_specs")
    if not isinstance(perf_specs, list) or not perf_specs:
        raise IterativeSizingContextError(
            "design_specs.performance_specs must be a non-empty array"
        )

    parsed: List[Dict[str, Any]] = []
    for idx, item in enumerate(perf_specs):
        if not isinstance(item, dict):
            raise IterativeSizingContextError(
                f"design_specs.performance_specs[{idx}] must be an object"
            )

        name = item.get("name")
        method = item.get("method")
        threshold = item.get("threshold")
        index = item.get("index")

        if not isinstance(name, str) or not name.strip():
            raise IterativeSizingContextError(f"design_specs.performance_specs[{idx}].name invalid")
        if method not in {"min", "max", "target"}:
            raise IterativeSizingContextError(
                f"design_specs.performance_specs[{idx}].method invalid"
            )
        if not isinstance(threshold, (int, float)):
            raise IterativeSizingContextError(
                f"design_specs.performance_specs[{idx}].threshold invalid"
            )
        if not isinstance(index, int):
            raise IterativeSizingContextError(
                f"design_specs.performance_specs[{idx}].index invalid"
            )

        parsed.append(
            {
                "name": name,
                "method": method,
                "threshold": float(threshold),
                "index": int(index),
            }
        )

    parsed.sort(key=lambda item: int(item["index"]))
    return parsed


def extract_perf_metrics_from_design_specs(design_specs_json: Any) -> List[str]:
    return [item["name"] for item in extract_performance_specs(design_specs_json)]


def filter_role_perf_facts(
    kb_role_perf_json: Any, target_metrics: Iterable[str]
) -> List[Dict[str, Any]]:
    metrics_set = normalize_metric_set(target_metrics)
    if not isinstance(kb_role_perf_json, dict):
        return []
    facts = kb_role_perf_json.get("facts")
    if not isinstance(facts, list):
        return []

    selected: List[Dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        metric = fact.get("metric")
        if isinstance(metric, str) and (
            not metrics_set or canonical_metric_name(metric) in metrics_set
        ):
            selected.append(fact)
    return selected


def filter_perf_tradeoff_facts(
    kb_perf_tradeoff_json: Any, target_metrics: Iterable[str]
) -> List[Dict[str, Any]]:
    metrics_set = normalize_metric_set(target_metrics)
    if not isinstance(kb_perf_tradeoff_json, dict):
        return []
    facts = kb_perf_tradeoff_json.get("facts")
    if not isinstance(facts, list):
        return []

    selected: List[Dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        subject = fact.get("subject")
        obj = fact.get("object")
        if (isinstance(subject, str) and canonical_metric_name(subject) in metrics_set) or (
            isinstance(obj, str) and canonical_metric_name(obj) in metrics_set
        ):
            selected.append(fact)
    return selected


def filter_substruct_param_perf_facts(
    kb_substruct_param_perf_json: Any,
    substructure_types: Iterable[str],
    *,
    allowed_metrics: Iterable[str] | None = None,
    role_variables: Iterable[str] | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    # Retained in the signature for caller compatibility. Retrieval is based
    # only on performance metric: tagger-generated structure labels are unstable,
    # and transferable KB parameter families need not match local variable names.
    del substructure_types
    del role_variables
    if not isinstance(kb_substruct_param_perf_json, dict):
        return {"facts": []}
    facts = kb_substruct_param_perf_json.get("facts")
    if not isinstance(facts, list):
        return {"facts": []}

    metrics_allowed = normalize_metric_set(allowed_metrics)
    selected: List[Dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        metric = fact.get("metric")
        if metrics_allowed and (
            not isinstance(metric, str) or canonical_metric_name(metric) not in metrics_allowed
        ):
            continue
        selected.append(fact)
    return {"facts": selected}


def extract_role_substructure_types(substructures: Sequence[Mapping[str, Any]]) -> List[str]:
    types: List[str] = []
    seen: set[str] = set()
    for sub in substructures:
        type_name = sub.get("type")
        if isinstance(type_name, str) and type_name.strip() and type_name not in seen:
            seen.add(type_name)
            types.append(type_name)
    return types


def extract_role_substructures(
    tagging_json: Any,
    role_name: str,
    settings_json: Any | None = None,
) -> List[Dict[str, Any]]:
    if not isinstance(tagging_json, dict):
        raise IterativeSizingContextError("tagging must be a JSON object")
    stage2 = tagging_json.get("stage2")
    if not isinstance(stage2, dict):
        raise IterativeSizingContextError("tagging.stage2 must be a JSON object")
    roles = stage2.get("roles")
    if not isinstance(roles, list):
        raise IterativeSizingContextError("tagging.stage2.roles must be an array")

    for role in roles:
        if not isinstance(role, dict):
            continue
        if role.get("name") != role_name:
            continue
        substructures = role.get("substructures")
        if not isinstance(substructures, list):
            return []
        return [item for item in substructures if isinstance(item, dict)]

    if role_name == SYNTHETIC_CONTROL_ROLE:
        variables = _extract_unowned_design_variables(tagging_json, settings_json or {})
        if not variables:
            raise IterativeSizingContextError(
                f"role '{role_name}' has no unowned settings variables"
            )
        return [
            {
                "type": "Global control settings",
                "base_type": "global_controls",
                "modifiers": ["testbench", "bias"],
                "devices": [],
                "evidence": "Synthetic role for settings variables not owned by structural netlist tagging.",
                "confidence": 1.0,
                "variables": [
                    {
                        "device": "global_settings",
                        "design_variables": variables,
                    }
                ],
            }
        ]

    raise IterativeSizingContextError(f"role '{role_name}' not found in tagging.stage2.roles")


def _trim_role_substructures_for_prompt(
    role_substructures: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    trimmed: List[Dict[str, Any]] = []
    for substructure in role_substructures:
        if not isinstance(substructure, Mapping):
            continue
        trimmed.append(
            {
                key: value
                for key, value in dict(substructure).items()
                if key not in {"evidence", "base_type", "modifiers"}
            }
        )
    return trimmed


def _extract_unowned_design_variables(tagging_json: Any, settings_json: Any) -> List[str]:
    des_vars = settings_json.get("des_vars") if isinstance(settings_json, dict) else None
    if not isinstance(des_vars, dict):
        return []
    tagged = set(_extract_tagged_design_variables(tagging_json))
    return [
        name
        for name in des_vars.keys()
        if isinstance(name, str) and name.strip() and name not in tagged
    ]


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


def extract_role_design_variables_from_substructures(
    substructures: Sequence[Mapping[str, Any]],
) -> List[str]:
    variables: List[str] = []
    seen: set[str] = set()

    for sub in substructures:
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


def extract_variable_bounds(
    settings_json: Any, variable_names: Iterable[str]
) -> Dict[str, List[float]]:
    if not isinstance(settings_json, dict):
        raise IterativeSizingContextError("settings must be a JSON object")
    des_vars = settings_json.get("des_vars")
    if not isinstance(des_vars, dict):
        raise IterativeSizingContextError("settings.des_vars must be a JSON object")

    bounds: Dict[str, List[float]] = {}
    for name in variable_names:
        if name not in des_vars:
            raise IterativeSizingContextError(f"settings.des_vars missing variable '{name}'")
        entry = des_vars[name]
        if not isinstance(entry, list) or len(entry) not in {2, 3}:
            raise IterativeSizingContextError(
                f"settings.des_vars.{name} must be [min,max] or [min,max,is_int]"
            )

        lower = float(entry[0])
        upper = float(entry[1])
        is_int = bool(entry[2]) if len(entry) == 3 else False
        bounds[name] = [lower, upper, 1.0 if is_int else 0.0]

    return bounds


def select_improving_design_slices(
    simulation_records_json: Any,
    *,
    design_var_order: Sequence[str],
    perf_order: Sequence[str],
    outputs_spec: Mapping[str, Any],
    objective_metric: str,
    latest_k: int,
    best_k: int,
) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(simulation_records_json, list):
        raise IterativeSizingContextError("simulation records must be a JSON array")

    parsed: List[Dict[str, Any]] = []
    for idx, item in enumerate(simulation_records_json):
        if not isinstance(item, dict):
            continue
        iter_idx = item.get("iter")
        parameters = item.get("parameters")
        performance = item.get("performance")
        if not isinstance(iter_idx, int):
            continue
        if not isinstance(parameters, list) or not isinstance(performance, list):
            continue
        if len(parameters) != len(design_var_order) or len(performance) != len(perf_order):
            continue

        score = item.get("objective")
        if not isinstance(score, (int, float)):
            score = item.get("validation")
        if not isinstance(score, (int, float)):
            score = float("inf")

        parsed.append(
            {
                "iter": iter_idx,
                "design_vars": map_parameter_vector(parameters, design_var_order),
                "performances": map_performance_vector(performance, perf_order),
                "fallback_score": float(score),
            }
        )

    for item in parsed:
        objective_score = item["performances"].get(objective_metric, item["fallback_score"])
        if not isinstance(objective_score, (int, float)):
            objective_score = item["fallback_score"]
        if not isinstance(objective_score, (int, float)):
            objective_score = float("inf")
        item["objective"] = float(objective_score)
        item["violation_count"] = count_violated_perfs(item["performances"], outputs_spec)
        item["violations"] = compute_weighted_violations(item["performances"], outputs_spec)
        item["weighted_sum"] = float(item["objective"]) + float(item["violations"])
        item.pop("fallback_score", None)

    parsed.sort(key=lambda item: item["iter"])
    improving: List[Dict[str, Any]] = []
    previous: Dict[str, Any] | None = None
    for item in parsed:
        if previous is not None and (
            item["violation_count"],
            item["violations"],
            item["objective"],
        ) < (
            previous["violation_count"],
            previous["violations"],
            previous["objective"],
        ):
            improving.append(
                {
                    "before_iter": int(previous["iter"]),
                    "after_iter": int(item["iter"]),
                    "before_design_vars": dict(previous["design_vars"]),
                    "after_design_vars": dict(item["design_vars"]),
                    "before_performances": dict(previous["performances"]),
                    "after_performances": dict(item["performances"]),
                    "before_violation_count": int(previous["violation_count"]),
                    "after_violation_count": int(item["violation_count"]),
                    "before_violations": float(previous["violations"]),
                    "after_violations": float(item["violations"]),
                    "before_weighted_sum": float(previous["weighted_sum"]),
                    "after_weighted_sum": float(item["weighted_sum"]),
                    "objective": float(item["objective"]),
                    "violation_count": int(item["violation_count"]),
                    "violations": float(item["violations"]),
                    "weighted_sum": float(item["weighted_sum"]),
                }
            )
        previous = item

    latest = list(reversed(improving))[: max(0, latest_k)]
    best = sorted(
        improving,
        key=lambda item: (
            item["violation_count"],
            item["violations"],
            item["objective"],
            item["weighted_sum"],
        ),
    )[: max(0, best_k)]

    return {
        "latest": latest,
        "best": best,
    }


def count_violated_perfs(performances: Mapping[str, Any], outputs_spec: Mapping[str, Any]) -> int:
    violations = 0
    for name, spec in outputs_spec.items():
        if name not in performances:
            continue
        value = performances[name]
        if not isinstance(value, (int, float)):
            continue
        if not isinstance(spec, list) or len(spec) < 2:
            continue

        threshold = spec[0]
        method = spec[1]
        if not isinstance(threshold, (int, float)) or not isinstance(method, str):
            continue

        if method == "min" and float(value) < float(threshold):
            violations += 1
        elif method == "max" and float(value) > float(threshold):
            violations += 1

    return violations


def compute_weighted_violations(
    performances: Mapping[str, Any], outputs_spec: Mapping[str, Any]
) -> float:
    total = 0.0
    for name, spec in outputs_spec.items():
        if name not in performances:
            continue
        value = performances[name]
        if not isinstance(value, (int, float)):
            continue
        if not isinstance(spec, list) or len(spec) < 2:
            continue

        threshold = spec[0]
        method = spec[1]
        weight = spec[2] if len(spec) >= 3 else 1.0
        if not isinstance(threshold, (int, float)) or not isinstance(method, str):
            continue
        if not isinstance(weight, (int, float)):
            weight = 1.0

        metric_value = float(value)
        metric_threshold = float(threshold)
        metric_weight = float(weight)

        if method == "min":
            total += max(metric_threshold - metric_value, 0.0) * metric_weight
        elif method == "max":
            total += max(metric_value - metric_threshold, 0.0) * metric_weight

    return float(total)
