from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Sequence

REGION_PREFIX = "region_"
GM_PATTERN = re.compile(r"^gm(?:m)?(\d+)$", re.IGNORECASE)
REGION_LABELS = {
    0: "cutoff",
    1: "triode",
    2: "saturation",
    3: "subthreshold",
}


def is_operation_region_metric(name: Any) -> bool:
    return isinstance(name, str) and name.strip().lower().startswith(REGION_PREFIX)


def is_gm_metric(name: Any) -> bool:
    return isinstance(name, str) and bool(GM_PATTERN.match(name.strip()))


def is_device_feedback_metric(name: Any) -> bool:
    return is_operation_region_metric(name) or is_gm_metric(name)


def extract_response_order(settings_json: Any) -> List[str]:
    if not isinstance(settings_json, Mapping):
        return []
    responses = settings_json.get("responses")
    if not isinstance(responses, Mapping):
        return []
    assembler = responses.get("assembler")
    if not isinstance(assembler, Sequence) or isinstance(assembler, (str, bytes)):
        return []
    return [str(item).strip() for item in assembler if isinstance(item, str) and item.strip()]


def filter_core_performance_metrics(metric_names: Iterable[str]) -> List[str]:
    return [
        name
        for name in metric_names
        if isinstance(name, str) and name.strip() and not is_device_feedback_metric(name)
    ]


def build_operation_region_summary_from_metric_map(metric_map: Mapping[str, Any]) -> Dict[str, Any]:
    device_regions: Dict[str, int] = {}
    device_gms: Dict[str, float] = {}
    histogram: Counter[str] = Counter()

    for name, value in metric_map.items():
        if is_operation_region_metric(name):
            if not isinstance(value, (int, float)):
                continue
            code = int(round(float(value)))
            device_name = _normalize_region_device_name(str(name))
            device_regions[device_name] = code
            histogram[str(code)] += 1
            continue
        if is_gm_metric(name):
            if not isinstance(value, (int, float)):
                continue
            device_name = _normalize_gm_device_name(str(name))
            device_gms[device_name] = float(value)

    return {
        "available_device_count": len(device_regions),
        "available_gm_device_count": len(device_gms),
        "region_code_histogram": dict(sorted(histogram.items())),
        "device_regions": device_regions,
        "device_gms": device_gms,
    }


def extract_operation_region_targets_from_settings(settings_json: Any) -> Dict[str, Any]:
    outputs = settings_json.get("outputs") if isinstance(settings_json, Mapping) else None
    if not isinstance(outputs, Mapping):
        return {
            "target_region_code": None,
            "target_region_by_device": {},
        }

    target_region_by_device: Dict[str, int] = {}
    target_codes: List[int] = []
    for name, raw in outputs.items():
        if not is_operation_region_metric(name):
            continue
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) < 1:
            continue
        threshold = raw[0]
        if not isinstance(threshold, (int, float)):
            continue
        code = int(round(float(threshold)))
        device_name = _normalize_region_device_name(str(name))
        target_region_by_device[device_name] = code
        target_codes.append(code)

    target_region_code = None
    if target_codes and len(set(target_codes)) == 1:
        target_region_code = target_codes[0]

    return {
        "target_region_code": target_region_code,
        "target_region_by_device": target_region_by_device,
    }


def filter_operation_region_summary_for_role(
    operation_region_summary: Mapping[str, Any] | None,
    role_substructures: Sequence[Mapping[str, Any]],
    target_region_targets: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    target_region_by_device = (
        target_region_targets.get("target_region_by_device", {})
        if isinstance(target_region_targets, Mapping)
        else {}
    )
    if not isinstance(target_region_by_device, Mapping):
        target_region_by_device = {}
    role_devices = _extract_role_devices(role_substructures)

    if not isinstance(operation_region_summary, Mapping):
        role_device_regions = []
        for device in role_devices:
            target_code = target_region_by_device.get(device)
            if isinstance(target_code, (int, float)):
                role_device_regions.append(
                    {
                        "device": device,
                        "target_region": _region_label(int(round(float(target_code)))),
                    }
                )
        return {
            "available_device_count": len(role_device_regions),
            "role_device_regions": role_device_regions,
            "role_device_gms": [],
        }

    device_regions = operation_region_summary.get("device_regions")
    if not isinstance(device_regions, Mapping):
        device_regions = {}
    device_gms = operation_region_summary.get("device_gms")
    if not isinstance(device_gms, Mapping):
        device_gms = {}
    role_device_regions = []
    role_device_gms = []

    for device in role_devices:
        raw_code = device_regions.get(device)
        if isinstance(raw_code, (int, float)):
            code = int(round(float(raw_code)))
            item = {"device": device, "region": _region_label(code)}
            target_code = target_region_by_device.get(device)
            if isinstance(target_code, (int, float)):
                item["target_region"] = _region_label(int(round(float(target_code))))
            role_device_regions.append(item)
        raw_gm = device_gms.get(device)
        if isinstance(raw_gm, (int, float)):
            role_device_gms.append({"device": device, "gm": float(raw_gm)})

    return {
        "available_device_count": len(role_device_regions),
        "role_device_regions": role_device_regions,
        "role_device_gms": role_device_gms,
    }


def build_role_operation_region_planner_summaries(
    operation_region_summary: Mapping[str, Any] | None,
    tagging_json: Any,
    settings_json: Any,
    allowed_roles: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    target_region_targets = extract_operation_region_targets_from_settings(settings_json)
    role_entries = _extract_role_entries_from_tagging(tagging_json)
    allowed = {role for role in (allowed_roles or []) if isinstance(role, str) and role.strip()}

    summaries: List[Dict[str, Any]] = []
    for entry in role_entries:
        role_name = entry["role_name"]
        if allowed and role_name not in allowed:
            continue
        filtered = filter_operation_region_summary_for_role(
            operation_region_summary,
            entry["substructures"],
            target_region_targets,
        )
        role_device_regions = filtered.get("role_device_regions", [])
        if not isinstance(role_device_regions, list):
            role_device_regions = []
        summaries.append(
            {
                "role_name": role_name,
                "role_device_regions": role_device_regions,
                "role_device_gms": filtered.get("role_device_gms", []),
            }
        )
    return summaries


def _normalize_region_device_name(metric_name: str) -> str:
    lowered = metric_name.strip()
    if lowered.lower().startswith(REGION_PREFIX):
        lowered = lowered[len(REGION_PREFIX) :]
    lowered = lowered.strip()
    if lowered.lower().startswith("m") and len(lowered) > 1:
        return f"M{lowered[1:]}"
    return lowered


def _normalize_gm_device_name(metric_name: str) -> str:
    match = GM_PATTERN.match(metric_name.strip())
    if not match:
        return metric_name.strip()
    return f"M{match.group(1)}"


def _extract_role_devices(role_substructures: Sequence[Mapping[str, Any]]) -> List[str]:
    devices: List[str] = []
    seen: set[str] = set()
    for substructure in role_substructures:
        if not isinstance(substructure, Mapping):
            continue
        sub_devices = substructure.get("devices")
        if not isinstance(sub_devices, Sequence) or isinstance(sub_devices, (str, bytes)):
            continue
        for device in sub_devices:
            if not isinstance(device, str):
                continue
            normalized = device.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            devices.append(normalized)
    return devices


def _extract_role_entries_from_tagging(tagging_json: Any) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if not isinstance(tagging_json, Mapping):
        return entries

    stage2 = tagging_json.get("stage2")
    roles2 = stage2.get("roles") if isinstance(stage2, Mapping) else None
    if isinstance(roles2, Sequence) and not isinstance(roles2, (str, bytes)):
        for role in roles2:
            if not isinstance(role, Mapping):
                continue
            role_name = role.get("name")
            substructures = role.get("substructures")
            if not isinstance(role_name, str) or not role_name.strip():
                continue
            if not isinstance(substructures, Sequence) or isinstance(substructures, (str, bytes)):
                continue
            entries.append(
                {
                    "role_name": role_name.strip(),
                    "substructures": [sub for sub in substructures if isinstance(sub, Mapping)],
                }
            )
        if entries:
            return entries

    stage1 = tagging_json.get("stage1")
    roles1 = stage1.get("functional_roles") if isinstance(stage1, Mapping) else None
    if isinstance(roles1, Sequence) and not isinstance(roles1, (str, bytes)):
        for role in roles1:
            if not isinstance(role, Mapping):
                continue
            role_name = role.get("name")
            devices = role.get("devices")
            if not isinstance(role_name, str) or not role_name.strip():
                continue
            substructure = {
                "type": "Role devices",
                "devices": list(devices)
                if isinstance(devices, Sequence) and not isinstance(devices, (str, bytes))
                else [],
            }
            entries.append(
                {
                    "role_name": role_name.strip(),
                    "substructures": [substructure],
                }
            )
    return entries


def _region_label(raw_code: Any) -> str | None:
    if not isinstance(raw_code, (int, float)):
        return None
    code = int(round(float(raw_code)))
    return REGION_LABELS.get(code, f"unknown({code})")
