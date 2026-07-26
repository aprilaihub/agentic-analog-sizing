from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

PLANNER_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "state_action",
        "target_metric",
        "selected_role_name",
        "worker_instruction",
        "selection_rationale",
        "recovery_rationale",
        "focus_kb_evidence",
    ],
    "properties": {
        "state_action": {
            "type": "string",
            "enum": ["continue_current", "revert_to_best_known"],
        },
        "target_metric": {"type": "string", "minLength": 1},
        "selected_role_name": {"type": "string", "minLength": 1},
        "worker_instruction": {"type": "string", "minLength": 1},
        "selection_rationale": {"type": "string", "minLength": 1},
        "recovery_rationale": {"type": "string", "minLength": 1},
        "focus_kb_evidence": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
    },
}


_WORKER_CANDIDATE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "updated_design_vars",
        "predicted_performances",
        "rationale",
    ],
    "properties": {
        "updated_design_vars": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "value", "reason"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "value": {"type": "number"},
                    "reason": {"type": "string", "minLength": 1},
                },
            },
        },
        "predicted_performances": {
            "type": "array",
            "minItems": 0,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "value", "reason"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "value": {"type": "number"},
                    "reason": {"type": "string", "minLength": 1},
                },
            },
        },
        "rationale": {"type": "string", "minLength": 1},
    },
}


def build_worker_output_schema(candidate_count: int) -> Dict[str, Any]:
    if candidate_count < 1:
        raise ValueError("candidate_count must be >= 1")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "role_name",
            "target_metric",
            "candidates",
            "rationale",
        ],
        "properties": {
            "role_name": {"type": "string", "minLength": 1},
            "target_metric": {"type": "string", "minLength": 1},
            "candidates": {
                "type": "array",
                "minItems": candidate_count,
                "maxItems": candidate_count,
                "items": _WORKER_CANDIDATE_SCHEMA,
            },
            "rationale": {"type": "string", "minLength": 1},
        },
    }


class IterativeSchemaValidationError(ValueError):
    """Raised when iterative planner/worker payload fails local validation."""


def validate_planner_payload(
    payload: Any,
    *,
    unsatisfied_metrics: Set[str],
    allowed_roles: Set[str],
) -> Dict[str, Any]:
    data = _require_dict(payload, "planner payload")
    _assert_keys(
        data,
        [
            "state_action",
            "target_metric",
            "selected_role_name",
            "worker_instruction",
            "selection_rationale",
            "recovery_rationale",
            "focus_kb_evidence",
        ],
        "planner payload",
    )

    state_action = _require_str(data.get("state_action"), "planner payload.state_action")
    if state_action not in {"continue_current", "revert_to_best_known"}:
        raise IterativeSchemaValidationError(
            "planner payload.state_action must be either 'continue_current' or 'revert_to_best_known'"
        )

    target_metric = _require_str(data.get("target_metric"), "planner payload.target_metric")
    if unsatisfied_metrics and target_metric not in unsatisfied_metrics:
        raise IterativeSchemaValidationError(
            f"planner payload.target_metric '{target_metric}' must be one of unsatisfied metrics: "
            f"{sorted(unsatisfied_metrics)}"
        )

    selected_role_name = _require_str(
        data.get("selected_role_name"),
        "planner payload.selected_role_name",
    )
    if selected_role_name not in allowed_roles:
        raise IterativeSchemaValidationError(
            f"planner payload.selected_role_name '{selected_role_name}' is not in allowed roles: "
            f"{sorted(allowed_roles)}"
        )

    worker_instruction = _require_str(
        data.get("worker_instruction"),
        "planner payload.worker_instruction",
    )
    selection_rationale = _require_str(
        data.get("selection_rationale"),
        "planner payload.selection_rationale",
    )
    recovery_rationale = _require_str(
        data.get("recovery_rationale"),
        "planner payload.recovery_rationale",
    )
    focus_kb_evidence = _all_strings(
        _require_list(data.get("focus_kb_evidence"), "planner payload.focus_kb_evidence"),
        "planner payload.focus_kb_evidence",
    )

    return {
        "state_action": state_action,
        "target_metric": target_metric,
        "selected_role_name": selected_role_name,
        "worker_instruction": worker_instruction,
        "selection_rationale": selection_rationale,
        "recovery_rationale": recovery_rationale,
        "focus_kb_evidence": focus_kb_evidence,
    }


def validate_worker_payload(
    payload: Any,
    *,
    expected_role_name: str,
    expected_target_metric: str,
    allowed_variables: Set[str],
    variable_bounds: Mapping[str, Sequence[float]],
    required_performance_metrics: Set[str],
    expected_candidate_count: int,
    require_predicted_performances: bool = False,
) -> Dict[str, Any]:
    data = _require_dict(payload, "worker payload")

    role_name = _require_str(data.get("role_name"), "worker payload.role_name")
    if role_name != expected_role_name:
        raise IterativeSchemaValidationError(
            f"worker payload.role_name mismatch: expected '{expected_role_name}', got '{role_name}'"
        )

    target_metric = _require_str(data.get("target_metric"), "worker payload.target_metric")
    if target_metric != expected_target_metric:
        raise IterativeSchemaValidationError(
            f"worker payload.target_metric mismatch: expected '{expected_target_metric}', got '{target_metric}'"
        )

    if "candidates" in data:
        _assert_keys(
            data, ["role_name", "target_metric", "candidates", "rationale"], "worker payload"
        )
        candidates_raw = _require_list(data.get("candidates"), "worker payload.candidates")
        if len(candidates_raw) != expected_candidate_count:
            raise IterativeSchemaValidationError(
                f"worker payload.candidates must contain exactly {expected_candidate_count} items, got {len(candidates_raw)}"
            )
        overall_rationale = _require_str(data.get("rationale"), "worker payload.rationale")
        normalized_candidates = [
            _normalize_worker_candidate(
                item,
                context=f"worker payload.candidates[{idx}]",
                allowed_variables=allowed_variables,
                variable_bounds=variable_bounds,
                required_performance_metrics=required_performance_metrics,
                require_predicted_performances=require_predicted_performances,
            )
            for idx, item in enumerate(candidates_raw)
        ]
    else:
        _assert_keys(
            data,
            [
                "role_name",
                "target_metric",
                "updated_design_vars",
                "rationale",
            ],
            "worker payload",
        )
        overall_rationale = _require_str(data.get("rationale"), "worker payload.rationale")
        normalized_candidates = [
            _normalize_worker_candidate(
                data,
                context="worker payload",
                allowed_variables=allowed_variables,
                variable_bounds=variable_bounds,
                required_performance_metrics=required_performance_metrics,
                require_predicted_performances=require_predicted_performances,
            )
        ]

    return {
        "role_name": role_name,
        "target_metric": target_metric,
        "candidates": normalized_candidates,
        "rationale": overall_rationale,
    }


def _normalize_worker_candidate(
    candidate: Any,
    *,
    context: str,
    allowed_variables: Set[str],
    variable_bounds: Mapping[str, Sequence[float]],
    required_performance_metrics: Set[str],
    require_predicted_performances: bool,
) -> Dict[str, Any]:
    data = _require_dict(candidate, context)
    _assert_candidate_keys(data, context)

    updates_raw = _require_list(data.get("updated_design_vars"), f"{context}.updated_design_vars")
    seen_vars: Set[str] = set()
    normalized_updates: List[Dict[str, Any]] = []

    for idx, item in enumerate(updates_raw):
        item_ctx = f"{context}.updated_design_vars[{idx}]"
        obj = _require_dict(item, item_ctx)
        _assert_keys(obj, ["name", "value", "reason"], item_ctx)

        name = _require_str(obj.get("name"), f"{item_ctx}.name")
        if name not in allowed_variables:
            raise IterativeSchemaValidationError(
                f"{item_ctx}.name '{name}' is not in role-owned variable set: {sorted(allowed_variables)}"
            )
        if name in seen_vars:
            raise IterativeSchemaValidationError(f"{item_ctx}.name duplicated: '{name}'")
        seen_vars.add(name)

        value = _require_number(obj.get("value"), f"{item_ctx}.value")
        reason = _require_str(obj.get("reason"), f"{item_ctx}.reason")

        bounds = variable_bounds.get(name)
        if bounds is None or len(bounds) < 3:
            raise IterativeSchemaValidationError(f"missing bounds for variable '{name}'")
        lower = float(bounds[0])
        upper = float(bounds[1])
        is_int = bool(bounds[2])

        if value < lower or value > upper:
            raise IterativeSchemaValidationError(
                f"{item_ctx}.value out of bounds [{lower}, {upper}] for '{name}': {value}"
            )

        normalized_value = float(int(round(value))) if is_int else float(value)
        normalized_updates.append({"name": name, "value": normalized_value, "reason": reason})

    perf_value = data.get("predicted_performances")
    if perf_value is None:
        raise IterativeSchemaValidationError(f"{context}.predicted_performances must be present")
    if not isinstance(perf_value, list):
        raise IterativeSchemaValidationError(
            f"{context}.predicted_performances must be a JSON array"
        )
    if not require_predicted_performances:
        normalized_perfs: List[Dict[str, Any]] = []
    elif not perf_value:
        raise IterativeSchemaValidationError(
            f"{context}.predicted_performances must include all metrics in llm prediction mode"
        )
    else:
        perf_raw = perf_value
        seen_metrics: Set[str] = set()
        normalized_perfs = []

        for idx, item in enumerate(perf_raw):
            item_ctx = f"{context}.predicted_performances[{idx}]"
            obj = _require_dict(item, item_ctx)
            _assert_keys(obj, ["name", "value", "reason"], item_ctx)

            metric_name = _require_str(obj.get("name"), f"{item_ctx}.name")
            if metric_name in seen_metrics:
                raise IterativeSchemaValidationError(f"{item_ctx}.name duplicated: '{metric_name}'")
            seen_metrics.add(metric_name)

            value = _require_number(obj.get("value"), f"{item_ctx}.value")
            reason = _require_str(obj.get("reason"), f"{item_ctx}.reason")
            normalized_perfs.append({"name": metric_name, "value": float(value), "reason": reason})

        if seen_metrics != required_performance_metrics:
            missing = sorted(required_performance_metrics - seen_metrics)
            extra = sorted(seen_metrics - required_performance_metrics)
            raise IterativeSchemaValidationError(
                f"worker predicted_performances coverage mismatch. missing={missing}, extra={extra}"
            )
        normalized_perfs.sort(key=lambda item: item["name"])

    rationale = _require_str(data.get("rationale"), f"{context}.rationale")

    normalized_updates.sort(key=lambda item: item["name"])

    return {
        "updated_design_vars": normalized_updates,
        "predicted_performances": normalized_perfs,
        "rationale": rationale,
    }


def _assert_keys(obj: Mapping[str, Any], required: Sequence[str], context: str) -> None:
    required_set = set(required)
    actual = set(obj.keys())
    missing = sorted(required_set - actual)
    extras = sorted(actual - required_set)
    if missing:
        raise IterativeSchemaValidationError(f"{context} missing required keys: {missing}")
    if extras:
        raise IterativeSchemaValidationError(f"{context} has unexpected keys: {extras}")


def _assert_candidate_keys(obj: Mapping[str, Any], context: str) -> None:
    required_set = {"updated_design_vars", "predicted_performances", "rationale"}
    allowed_set = {"updated_design_vars", "predicted_performances", "rationale"}
    actual = set(obj.keys())
    missing = sorted(required_set - actual)
    extras = sorted(actual - allowed_set)
    if missing:
        raise IterativeSchemaValidationError(f"{context} missing required keys: {missing}")
    if extras:
        raise IterativeSchemaValidationError(f"{context} has unexpected keys: {extras}")


def _require_dict(value: Any, context: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise IterativeSchemaValidationError(f"{context} must be a JSON object")
    return value


def _require_list(value: Any, context: str) -> List[Any]:
    if not isinstance(value, list) or not value:
        raise IterativeSchemaValidationError(f"{context} must be a non-empty list")
    return value


def _require_str(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IterativeSchemaValidationError(f"{context} must be a non-empty string")
    return value.strip()


def _require_number(value: Any, context: str) -> float:
    if not isinstance(value, (int, float)):
        raise IterativeSchemaValidationError(f"{context} must be a number")
    return float(value)


def _all_strings(items: Iterable[Any], context: str) -> List[str]:
    result: List[str] = []
    for idx, item in enumerate(items):
        result.append(_require_str(item, f"{context}[{idx}]"))
    return result
