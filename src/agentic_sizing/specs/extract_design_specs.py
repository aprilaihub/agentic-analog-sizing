from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.operation_region import is_device_feedback_metric
from ..resources import read_text

RULE_MAPPING = {
    "min": ">=",
    "max": "<=",
    "target": "target",
}


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON array")
    return value


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _require_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    return float(value)


def _infer_topology(input_settings_path: Path) -> str:
    stem = input_settings_path.stem
    if stem.endswith("_settings"):
        stem = stem[: -len("_settings")]
    topology = stem.strip()
    if not topology:
        raise ValueError(f"Cannot infer topology from input filename: {input_settings_path.name}")
    return topology


def load_specs_extractor_prompt() -> str:
    prompt = read_text("prompts", "specs", "specs_extractor.md").strip()
    if not prompt:
        raise ValueError("Specs extractor prompt is empty")
    return prompt


def render_specs_extractor_prompt(settings: dict[str, Any], topology: str) -> str:
    template = load_specs_extractor_prompt()
    rendered = template.replace("{{TOPOLOGY}}", topology).replace(
        "{{SETTINGS_JSON}}",
        json.dumps(settings, indent=2, ensure_ascii=True),
    )
    return rendered


def extract_design_specs_from_settings(settings: dict[str, Any], topology: str) -> dict[str, Any]:
    settings = _require_dict(settings, "settings")
    topology = _require_string(topology, "topology")

    des_vars = _require_dict(settings.get("des_vars"), "settings.des_vars")
    responses = _require_dict(settings.get("responses"), "settings.responses")
    outputs = _require_dict(settings.get("outputs"), "settings.outputs")
    objective = _require_dict(settings.get("objective"), "settings.objective")

    metrics = _require_list(responses.get("assembler"), "settings.responses.assembler")
    metric_names: list[str] = []
    for i, item in enumerate(metrics):
        metric_name = _require_string(item, f"settings.responses.assembler[{i}]")
        if is_device_feedback_metric(metric_name):
            continue
        metric_names.append(metric_name)

    if not metric_names:
        raise ValueError("settings.responses.assembler must contain at least one metric")

    objective_metric = _require_string(objective.get("name"), "settings.objective.name")
    objective_sense = _require_string(objective.get("minormax"), "settings.objective.minormax")
    if objective_sense not in {"min", "max"}:
        raise ValueError("settings.objective.minormax must be 'min' or 'max'")
    if objective_metric not in metric_names:
        raise ValueError(
            f"settings.objective.name '{objective_metric}' not found in settings.responses.assembler"
        )

    design_variables: list[dict[str, Any]] = []
    for var_name, raw_range in des_vars.items():
        name = _require_string(var_name, "settings.des_vars key")
        value_range = _require_list(raw_range, f"settings.des_vars.{name}")
        if len(value_range) not in {2, 3}:
            raise ValueError(f"settings.des_vars.{name} must have length 2 or 3")

        min_value = _require_number(value_range[0], f"settings.des_vars.{name}[0]")
        max_value = _require_number(value_range[1], f"settings.des_vars.{name}[1]")
        if min_value > max_value:
            raise ValueError(f"settings.des_vars.{name} has min > max")

        is_int_flag = 0 if len(value_range) == 2 else value_range[2]
        if not isinstance(is_int_flag, (int, float, bool)):
            raise ValueError(f"settings.des_vars.{name}[2] must be numeric/bool")

        design_variables.append(
            {
                "name": name,
                "min": min_value,
                "max": max_value,
                "is_integer": bool(is_int_flag),
            }
        )

    performance_specs: list[dict[str, Any]] = []
    for index, metric in enumerate(metric_names):
        if metric not in outputs:
            raise ValueError(f"settings.outputs missing metric '{metric}'")

        spec = _require_list(outputs[metric], f"settings.outputs.{metric}")
        if len(spec) < 4:
            raise ValueError(f"settings.outputs.{metric} must have at least 4 items")

        threshold = _require_number(spec[0], f"settings.outputs.{metric}[0]")
        method = _require_string(spec[1], f"settings.outputs.{metric}[1]")
        weight = _require_number(spec[2], f"settings.outputs.{metric}[2]")
        calc_expr = _require_string(spec[3], f"settings.outputs.{metric}[3]")

        if method not in RULE_MAPPING:
            raise ValueError(
                f"settings.outputs.{metric}[1] method '{method}' must be one of {sorted(RULE_MAPPING.keys())}"
            )

        performance_specs.append(
            {
                "name": metric,
                "index": index,
                "method": method,
                "rule": RULE_MAPPING[method],
                "threshold": threshold,
                "weight": weight,
                "calc_expr": calc_expr,
                "is_objective": metric == objective_metric,
            }
        )

    return {
        "schema_version": "1.0.0",
        "topology": topology,
        "objective": {
            "metric": objective_metric,
            "sense": objective_sense,
        },
        "design_variables": design_variables,
        "performance_specs": performance_specs,
    }


def extract_design_specs_file(
    input_settings_path: str, output_path: str | None = None
) -> dict[str, Any]:
    input_path = Path(input_settings_path).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input settings file not found: {input_path}")

    try:
        settings = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Input settings must be valid JSON: {input_path}") from exc

    topology = _infer_topology(input_path)
    # Keep prompt as an explicit runtime dependency of this tool.
    _ = render_specs_extractor_prompt(settings=settings, topology=topology)
    payload = extract_design_specs_from_settings(settings, topology)

    if output_path is None:
        output = input_path.with_name(f"{topology}_design_specs.json")
    else:
        output = Path(output_path).expanduser().resolve()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return payload
