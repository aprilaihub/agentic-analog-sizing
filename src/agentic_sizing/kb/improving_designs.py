from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


def generate_improving_designs(
    *,
    settings_path: str,
    simulation_record_path: str,
    output_path: str,
    max_points: int = 20,
) -> list[dict[str, Any]]:
    """Build a compact, constraint-first best trace from simulation history."""
    if max_points < 2:
        raise ValueError("max_points must be at least 2")

    settings = _load_json_object(settings_path, "settings")
    records = _load_json_array(simulation_record_path, "simulation record")
    parameter_count = len(_require_mapping(settings.get("des_vars"), "settings.des_vars"))
    metrics = _metric_order(settings)
    objective_name, objective_sense = _objective(settings)
    objective_index = metrics.index(objective_name)

    normalized: list[dict[str, Any]] = []
    seen_iters: set[int] = set()
    for index, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            raise ValueError(f"simulation record[{index}] must be an object")
        iteration = raw.get("iter")
        if not isinstance(iteration, int) or isinstance(iteration, bool) or iteration < 0:
            raise ValueError(f"simulation record[{index}].iter must be an integer >= 0")
        if iteration in seen_iters:
            raise ValueError(f"simulation record contains duplicate iter {iteration}")
        seen_iters.add(iteration)

        parameters = _numeric_vector(
            raw.get("parameters"), f"simulation record[{index}].parameters"
        )
        performance = _numeric_vector(
            raw.get("performance"), f"simulation record[{index}].performance"
        )
        if len(parameters) != parameter_count:
            raise ValueError(
                f"simulation record[{index}] parameter dimension mismatch: "
                f"got {len(parameters)}, expected {parameter_count}"
            )
        if len(performance) != len(metrics):
            raise ValueError(
                f"simulation record[{index}] performance dimension mismatch: "
                f"got {len(performance)}, expected {len(metrics)}"
            )

        objective = performance[objective_index]
        violations = _weighted_violations(performance, metrics, settings, objective_name)
        normalized.append(
            {
                "iter": iteration,
                "parameters": parameters,
                "performance": performance,
                "validation": objective + violations,
                "objective": objective,
                "violations": violations,
            }
        )

    normalized.sort(key=lambda item: item["iter"])
    improving: list[dict[str, Any]] = []
    best_score: tuple[float, float] | None = None
    for item in normalized:
        objective_score = item["objective"] if objective_sense == "min" else -item["objective"]
        score = (item["violations"], objective_score)
        if best_score is None or score < best_score:
            improving.append(item)
            best_score = score

    improving = _evenly_limit(improving, max_points)
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(improving, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return improving


def _weighted_violations(
    performance: Sequence[float],
    metrics: Sequence[str],
    settings: Mapping[str, Any],
    objective_name: str,
) -> float:
    outputs = _require_mapping(settings.get("outputs"), "settings.outputs")
    total = 0.0
    for index, metric in enumerate(metrics):
        if metric == objective_name:
            continue
        spec = outputs.get(metric)
        if not isinstance(spec, list) or len(spec) < 3:
            raise ValueError(
                f"settings.outputs.{metric} must contain threshold, method, and weight"
            )
        threshold, method, weight = float(spec[0]), str(spec[1]).lower(), float(spec[2])
        value = performance[index]
        if method == "min":
            total += max(threshold - value, 0.0) * weight
        elif method == "max":
            total += max(value - threshold, 0.0) * weight
        elif method != "target":
            raise ValueError(f"settings.outputs.{metric} has unsupported method '{method}'")
    return total


def _metric_order(settings: Mapping[str, Any]) -> list[str]:
    responses = _require_mapping(settings.get("responses"), "settings.responses")
    metrics = responses.get("assembler")
    if (
        not isinstance(metrics, list)
        or not metrics
        or not all(isinstance(x, str) and x for x in metrics)
    ):
        raise ValueError("settings.responses.assembler must be a non-empty string array")
    return list(metrics)


def _objective(settings: Mapping[str, Any]) -> tuple[str, str]:
    objective = _require_mapping(settings.get("objective"), "settings.objective")
    name, sense = objective.get("name"), objective.get("minormax")
    if not isinstance(name, str) or not name:
        raise ValueError("settings.objective.name must be a non-empty string")
    if sense not in {"min", "max"}:
        raise ValueError("settings.objective.minormax must be 'min' or 'max'")
    if name not in _metric_order(settings):
        raise ValueError(f"objective metric '{name}' is absent from settings.responses.assembler")
    return name, sense


def _evenly_limit(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(items) <= limit:
        return items
    indices = [round(i * (len(items) - 1) / (limit - 1)) for i in range(limit)]
    return [items[index] for index in indices]


def _numeric_vector(value: Any, field: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty numeric array")
    result: list[float] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
        ):
            raise ValueError(f"{field}[{index}] must be a finite number")
        result.append(float(item))
    return result


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _load_json_object(path: str, label: str) -> Mapping[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    return _require_mapping(value, label)


def _load_json_array(path: str, label: str) -> list[Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty JSON array")
    return value
