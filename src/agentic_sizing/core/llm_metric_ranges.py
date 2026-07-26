from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Sequence

from .operation_region import is_device_feedback_metric


def build_llm_metric_ranges_from_outputs(outputs_spec: Any) -> List[Dict[str, Any]]:
    specs_by_name = _outputs_to_specs_by_name(outputs_spec)
    return _build_llm_metric_ranges(specs_by_name)


def annotate_design_specs_for_llm(design_specs_json: Any) -> Any:
    if not isinstance(design_specs_json, dict):
        return design_specs_json

    perf_specs = design_specs_json.get("performance_specs")
    if not isinstance(perf_specs, list):
        return design_specs_json

    specs_by_name: Dict[str, Dict[str, Any]] = {}
    for item in perf_specs:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        method = item.get("method")
        threshold = item.get("threshold")
        if (
            not isinstance(name, str)
            or not isinstance(method, str)
            or not isinstance(threshold, (int, float))
        ):
            continue
        specs_by_name[name] = {
            "method": method,
            "threshold": float(threshold),
        }

    prompt_design_specs = deepcopy(design_specs_json)
    prompt_perf_specs = prompt_design_specs.get("performance_specs")
    if isinstance(prompt_perf_specs, list):
        slim_specs: List[Dict[str, Any]] = []
        llm_metric_ranges = _build_llm_metric_ranges(specs_by_name)
        annotations = _range_annotations_by_metric(llm_metric_ranges)
        for item in prompt_perf_specs:
            if not isinstance(item, dict):
                continue
            normalized = {
                key: item[key] for key in ("name", "index", "method", "threshold") if key in item
            }
            name = normalized.get("name")
            if isinstance(name, str) and name in annotations:
                normalized.update(annotations[name])
            slim_specs.append(normalized)
        prompt_design_specs["performance_specs"] = slim_specs
    llm_metric_ranges = _build_llm_metric_ranges(specs_by_name)
    if llm_metric_ranges:
        prompt_design_specs["llm_metric_ranges"] = llm_metric_ranges
    return prompt_design_specs


def annotate_settings_for_llm(settings_json: Any) -> Any:
    if not isinstance(settings_json, dict):
        return settings_json

    llm_metric_ranges = build_llm_metric_ranges_from_outputs(settings_json.get("outputs"))
    if not llm_metric_ranges:
        return settings_json

    prompt_settings = deepcopy(settings_json)
    prompt_settings["llm_metric_ranges"] = llm_metric_ranges
    return prompt_settings


def annotate_metric_items_for_llm(
    metric_items: Sequence[Mapping[str, Any]],
    outputs_spec: Any,
) -> List[Dict[str, Any]]:
    llm_metric_ranges = build_llm_metric_ranges_from_outputs(outputs_spec)
    if not llm_metric_ranges:
        return [dict(item) for item in metric_items if isinstance(item, Mapping)]

    annotations = _range_annotations_by_metric(llm_metric_ranges)
    annotated: List[Dict[str, Any]] = []
    for item in metric_items:
        if not isinstance(item, Mapping):
            continue
        normalized = dict(item)
        name = normalized.get("name")
        if isinstance(name, str) and name in annotations:
            normalized.update(annotations[name])
        annotated.append(normalized)
    return annotated


def _outputs_to_specs_by_name(outputs_spec: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(outputs_spec, Mapping):
        return {}

    specs_by_name: Dict[str, Dict[str, Any]] = {}
    for name, raw in outputs_spec.items():
        if (
            not isinstance(name, str)
            or is_device_feedback_metric(name)
            or not isinstance(raw, Sequence)
            or len(raw) < 2
        ):
            continue
        threshold = raw[0]
        method = raw[1]
        if not isinstance(threshold, (int, float)) or not isinstance(method, str):
            continue
        specs_by_name[name] = {
            "method": method,
            "threshold": float(threshold),
        }
    return specs_by_name


def _build_llm_metric_ranges(
    specs_by_name: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    llm_metric_ranges: List[Dict[str, Any]] = []
    for lower_name, lower_spec in specs_by_name.items():
        if not isinstance(lower_name, str) or lower_name.endswith("2"):
            continue
        upper_name = f"{lower_name}2"
        upper_spec = specs_by_name.get(upper_name)
        if upper_spec is None:
            continue

        lower_method = lower_spec.get("method")
        upper_method = upper_spec.get("method")
        lower_threshold = lower_spec.get("threshold")
        upper_threshold = upper_spec.get("threshold")
        if lower_method != "min" or upper_method != "max":
            continue
        if not isinstance(lower_threshold, (int, float)) or not isinstance(
            upper_threshold, (int, float)
        ):
            continue

        llm_metric_ranges.append(
            {
                "shared_metric_name": lower_name,
                "lower_bound_metric": lower_name,
                "upper_bound_metric": upper_name,
                "range_min": float(lower_threshold),
                "range_max": float(upper_threshold),
                "note": (
                    f"For LLM reasoning, treat {lower_name} and {upper_name} as the lower and upper "
                    f"bounds of the same physical metric {lower_name}. Keep the raw metrics unchanged "
                    "for validation and violation calculation."
                ),
            }
        )

    llm_metric_ranges.sort(key=lambda item: str(item["shared_metric_name"]))
    return llm_metric_ranges


def _range_annotations_by_metric(
    llm_metric_ranges: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    annotations: Dict[str, Dict[str, Any]] = {}
    for item in llm_metric_ranges:
        shared_metric_name = item.get("shared_metric_name")
        lower_bound_metric = item.get("lower_bound_metric")
        upper_bound_metric = item.get("upper_bound_metric")
        range_min = item.get("range_min")
        range_max = item.get("range_max")
        note = item.get("note")
        if not all(
            isinstance(value, str) and value
            for value in (shared_metric_name, lower_bound_metric, upper_bound_metric)
        ):
            continue
        if not isinstance(range_min, (int, float)) or not isinstance(range_max, (int, float)):
            continue
        if not isinstance(note, str):
            continue

        shared = {
            "llm_shared_metric_name": shared_metric_name,
            "llm_range_min": float(range_min),
            "llm_range_max": float(range_max),
            "llm_note": note,
        }
        annotations[lower_bound_metric] = {
            **shared,
            "llm_bound_role": "lower_bound",
        }
        annotations[upper_bound_metric] = {
            **shared,
            "llm_bound_role": "upper_bound",
        }
    return annotations
