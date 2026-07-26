from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

PLANNER_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["role_execution_plan"],
    "properties": {
        "role_execution_plan": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "role_name",
                    "priority_rank",
                    "importance_rationale",
                    "worker_instruction",
                    "focus_metrics",
                ],
                "properties": {
                    "role_name": {"type": "string", "minLength": 1},
                    "priority_rank": {"type": "integer", "minimum": 1},
                    "importance_rationale": {"type": "string", "minLength": 1},
                    "worker_instruction": {"type": "string", "minLength": 1},
                    "focus_metrics": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
        }
    },
}


WORKER_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["role_name", "assignments", "rationale"],
    "properties": {
        "role_name": {"type": "string", "minLength": 1},
        "assignments": {
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
        "rationale": {"type": "string", "minLength": 1},
    },
}


SIMULATION_RECORD_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["iter", "parameters", "performance"],
    "properties": {
        "iter": {"type": "integer", "minimum": 1},
        "parameters": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "number"},
        },
        "performance": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "number"},
        },
        "cost_time_s": {"type": "number", "minimum": 0},
    },
}


SIMULATION_RECORD_FILE_SCHEMA: Dict[str, Any] = {
    "type": "array",
    "items": SIMULATION_RECORD_SCHEMA,
}


class InitializeSchemaValidationError(ValueError):
    """Raised when initialize payload does not satisfy schema-level constraints."""


def validate_planner_payload(
    payload: Any,
    *,
    allowed_roles: Set[str],
    allowed_metrics: Set[str],
) -> Dict[str, Any]:
    data = _require_dict(payload, "planner payload")
    _assert_keys(data, ["role_execution_plan"], "planner payload")

    plan = _require_list(data.get("role_execution_plan"), "planner payload.role_execution_plan")
    seen_roles: Set[str] = set()
    seen_ranks: Set[int] = set()
    normalized: List[Dict[str, Any]] = []

    for idx, item in enumerate(plan):
        ctx = f"planner payload.role_execution_plan[{idx}]"
        obj = _require_dict(item, ctx)
        _assert_keys(
            obj,
            [
                "role_name",
                "priority_rank",
                "importance_rationale",
                "worker_instruction",
                "focus_metrics",
            ],
            ctx,
        )

        role_name = _require_str(obj.get("role_name"), f"{ctx}.role_name")
        if role_name not in allowed_roles:
            raise InitializeSchemaValidationError(
                f"{ctx}.role_name '{role_name}' is not in tagging functional roles."
            )
        if role_name in seen_roles:
            raise InitializeSchemaValidationError(f"{ctx}.role_name duplicated: '{role_name}'.")
        seen_roles.add(role_name)

        rank = _require_positive_int(obj.get("priority_rank"), f"{ctx}.priority_rank")
        if rank in seen_ranks:
            raise InitializeSchemaValidationError(f"{ctx}.priority_rank duplicated: {rank}.")
        seen_ranks.add(rank)

        importance_rationale = _require_str(
            obj.get("importance_rationale"), f"{ctx}.importance_rationale"
        )
        worker_instruction = _require_str(
            obj.get("worker_instruction"), f"{ctx}.worker_instruction"
        )

        focus_metrics = _all_strings(
            _require_list(obj.get("focus_metrics"), f"{ctx}.focus_metrics"),
            f"{ctx}.focus_metrics",
        )
        bad_focus = [metric for metric in focus_metrics if metric not in allowed_metrics]
        if bad_focus:
            raise InitializeSchemaValidationError(
                f"{ctx}.focus_metrics contains unknown metrics: {sorted(set(bad_focus))}."
            )

        normalized.append(
            {
                "role_name": role_name,
                "priority_rank": rank,
                "importance_rationale": importance_rationale,
                "worker_instruction": worker_instruction,
                "focus_metrics": focus_metrics,
            }
        )

    if seen_roles != allowed_roles:
        missing = sorted(allowed_roles - seen_roles)
        extra = sorted(seen_roles - allowed_roles)
        raise InitializeSchemaValidationError(
            f"planner role coverage mismatch. missing={missing}, extra={extra}."
        )

    expected_ranks = set(range(1, len(plan) + 1))
    if seen_ranks != expected_ranks:
        raise InitializeSchemaValidationError(
            f"priority_rank must be contiguous 1..{len(plan)}. got={sorted(seen_ranks)}."
        )

    normalized.sort(key=lambda item: item["priority_rank"])
    return {"role_execution_plan": normalized}


def validate_worker_payload(
    payload: Any,
    *,
    role_name: str,
    allowed_variables: Set[str],
    variable_bounds: Mapping[str, Sequence[float]],
) -> Dict[str, Any]:
    data = _require_dict(payload, "worker payload")
    _assert_keys(data, ["role_name", "assignments", "rationale"], "worker payload")

    payload_role = _require_str(data.get("role_name"), "worker payload.role_name")
    if payload_role != role_name:
        raise InitializeSchemaValidationError(
            f"worker payload.role_name mismatch: expected '{role_name}', got '{payload_role}'."
        )

    assignments = _require_list(data.get("assignments"), "worker payload.assignments")
    seen_vars: Set[str] = set()
    normalized_assignments: List[Dict[str, Any]] = []

    for idx, item in enumerate(assignments):
        ctx = f"worker payload.assignments[{idx}]"
        obj = _require_dict(item, ctx)
        _assert_keys(obj, ["name", "value", "reason"], ctx)

        name = _require_str(obj.get("name"), f"{ctx}.name")
        if name not in allowed_variables:
            raise InitializeSchemaValidationError(
                f"{ctx}.name '{name}' is not allowed for role '{role_name}'."
            )
        if name in seen_vars:
            raise InitializeSchemaValidationError(f"{ctx}.name duplicated: '{name}'.")
        seen_vars.add(name)

        value = _require_number(obj.get("value"), f"{ctx}.value")
        reason = _require_str(obj.get("reason"), f"{ctx}.reason")

        bounds = variable_bounds.get(name)
        if bounds is None or len(bounds) < 2:
            raise InitializeSchemaValidationError(f"Missing bounds for variable '{name}'.")
        lower = float(bounds[0])
        upper = float(bounds[1])
        if value < lower or value > upper:
            raise InitializeSchemaValidationError(
                f"{ctx}.value out of range [{lower}, {upper}] for '{name}': {value}."
            )

        normalized_assignments.append({"name": name, "value": value, "reason": reason})

    if seen_vars != allowed_variables:
        missing = sorted(allowed_variables - seen_vars)
        extra = sorted(seen_vars - allowed_variables)
        raise InitializeSchemaValidationError(
            f"worker assignment coverage mismatch for role '{role_name}'. missing={missing}, extra={extra}."
        )

    rationale = _require_str(data.get("rationale"), "worker payload.rationale")
    normalized_assignments.sort(key=lambda item: item["name"])
    return {
        "role_name": payload_role,
        "assignments": normalized_assignments,
        "rationale": rationale,
    }


def validate_simulation_record(record: Any) -> Dict[str, Any]:
    obj = _require_dict(record, "simulation record")
    _assert_keys(
        obj,
        ["iter", "parameters", "performance"],
        "simulation record",
        optional=["cost_time_s"],
    )

    iter_idx = _require_positive_int(obj.get("iter"), "simulation record.iter")
    parameters = _require_number_list(obj.get("parameters"), "simulation record.parameters")
    performance = _require_number_list(obj.get("performance"), "simulation record.performance")
    cost_time_s = obj.get("cost_time_s")

    if not parameters:
        raise InitializeSchemaValidationError("simulation record.parameters must not be empty.")
    if not performance:
        raise InitializeSchemaValidationError("simulation record.performance must not be empty.")
    if cost_time_s is not None:
        cost_time_s = _require_non_negative_number(cost_time_s, "simulation record.cost_time_s")

    normalized = {
        "iter": iter_idx,
        "parameters": parameters,
        "performance": performance,
    }
    if cost_time_s is not None:
        normalized["cost_time_s"] = cost_time_s
    return normalized


def validate_simulation_record_file(records: Any) -> List[Dict[str, Any]]:
    arr = _require_list(records, "simulation record file")
    normalized: List[Dict[str, Any]] = []
    last_iter = 0
    for idx, record in enumerate(arr):
        parsed = validate_simulation_record(record)
        if parsed["iter"] <= last_iter:
            raise InitializeSchemaValidationError(
                f"simulation record file iter must be strictly increasing at index {idx}."
            )
        last_iter = parsed["iter"]
        normalized.append(parsed)
    return normalized


def _assert_keys(
    obj: Mapping[str, Any],
    required: Sequence[str],
    context: str,
    *,
    optional: Sequence[str] = (),
) -> None:
    required_set = set(required)
    optional_set = set(optional)
    keys = set(obj.keys())
    missing = sorted(required_set - keys)
    extras = sorted(keys - required_set - optional_set)
    if missing:
        raise InitializeSchemaValidationError(f"{context} missing required keys: {missing}")
    if extras:
        raise InitializeSchemaValidationError(f"{context} contains unknown keys: {extras}")


def _require_dict(value: Any, field: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise InitializeSchemaValidationError(f"{field} must be an object.")
    return value


def _require_list(value: Any, field: str) -> List[Any]:
    if not isinstance(value, list):
        raise InitializeSchemaValidationError(f"{field} must be an array.")
    return value


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InitializeSchemaValidationError(f"{field} must be a non-empty string.")
    return value


def _all_strings(values: Iterable[Any], field: str) -> List[str]:
    items = list(values)
    bad = [item for item in items if not isinstance(item, str) or not item.strip()]
    if bad:
        raise InitializeSchemaValidationError(f"{field} must contain only non-empty strings.")
    return items  # type: ignore[return-value]


def _require_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or value < 1:
        raise InitializeSchemaValidationError(f"{field} must be an integer >= 1.")
    return value


def _require_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)):
        raise InitializeSchemaValidationError(f"{field} must be a number.")
    return float(value)


def _require_non_negative_number(value: Any, field: str) -> float:
    number = _require_number(value, field)
    if number < 0:
        raise InitializeSchemaValidationError(f"{field} must be >= 0.")
    return number


def _require_number_list(value: Any, field: str) -> List[float]:
    items = _require_list(value, field)
    parsed: List[float] = []
    for idx, item in enumerate(items):
        parsed.append(_require_number(item, f"{field}[{idx}]"))
    return parsed
