from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Mapping, Sequence

from ..core.metric_aliases import canonical_metric_name, normalize_metric_set
from ..workflow.state import PROJECT_ROOT

_PRIORITY_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

CRITICAL_HEURISTICS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["heuristics"],
    "properties": {
        "heuristics": {
            "type": "array",
            "minItems": 3,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["case_name", "condition", "heuristic", "priority", "scope"],
                "properties": {
                    "case_name": {"type": "string", "minLength": 1},
                    "condition": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["target_metrics"],
                        "properties": {
                            "target_metrics": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "minLength": 1},
                            }
                        },
                    },
                    "heuristic": {"type": "string", "minLength": 20},
                    "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "scope": {"type": "string", "enum": ["planner", "worker", "both"]},
                },
            },
        }
    },
}


def critical_heuristics_path(case_name: str, *, base_dir: str | Path | None = None) -> Path:
    root = (
        Path(base_dir).expanduser().resolve()
        if base_dir is not None
        else PROJECT_ROOT / "output" / "critical_heuristics"
    )
    return root / f"{case_name}_critical_heuristics.json"


def retrieve_critical_heuristics(
    *,
    case_name: str,
    target_metric: str | None = None,
    target_metrics: Sequence[str] | None = None,
    scope: str | None = None,
    base_dir: str | Path | None = None,
    max_items: int = 5,
) -> List[str]:
    items = [
        *load_critical_heuristics(case_name="global", base_dir=base_dir),
        *load_critical_heuristics(case_name=case_name, base_dir=base_dir),
    ]
    target_metric_set = normalize_metric_set(target_metrics)
    if target_metric and target_metric.strip():
        target_metric_set.add(canonical_metric_name(target_metric))
    matched = [
        item
        for item in items
        if _condition_matches(item.get("condition"), target_metrics=target_metric_set)
        and _scope_matches(item.get("scope"), scope=scope)
        and isinstance(item.get("heuristic"), str)
        and item.get("heuristic", "").strip()
    ]
    deduplicated = _deduplicate_heuristics(matched)
    deduplicated.sort(
        key=lambda item: (
            _PRIORITY_RANK.get(str(item.get("priority", "")).strip().lower(), 99),
            str(item.get("heuristic", "")),
        )
    )
    return [str(item["heuristic"]).strip() for item in deduplicated[: max(0, max_items)]]


def validate_critical_heuristics_payload(
    payload: Any,
    *,
    case_name: str,
    allowed_metrics: set[str],
) -> List[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("heuristics"), list):
        raise ValueError("critical heuristics payload must contain a heuristics array")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(payload["heuristics"]):
        if not isinstance(item, Mapping):
            raise ValueError(f"heuristics[{index}] must be an object")
        if set(item) != {"case_name", "condition", "heuristic", "priority", "scope"}:
            raise ValueError(f"heuristics[{index}] has invalid fields")
        if item.get("case_name") != case_name:
            raise ValueError(f"heuristics[{index}].case_name must equal {case_name!r}")
        condition = item.get("condition")
        target_metrics = condition.get("target_metrics") if isinstance(condition, Mapping) else None
        if not isinstance(target_metrics, list) or not target_metrics:
            raise ValueError(f"heuristics[{index}].condition.target_metrics must be non-empty")
        if any(metric not in allowed_metrics for metric in target_metrics):
            raise ValueError(f"heuristics[{index}] contains an unknown target metric")
        text = item.get("heuristic")
        if not isinstance(text, str) or len(text.strip()) < 20:
            raise ValueError(f"heuristics[{index}].heuristic is too short")
        priority = item.get("priority")
        scope = item.get("scope")
        if priority not in _PRIORITY_RANK:
            raise ValueError(f"heuristics[{index}].priority is invalid")
        if scope not in {"planner", "worker", "both"}:
            raise ValueError(f"heuristics[{index}].scope is invalid")
        normalized.append(
            {
                "case_name": case_name,
                "condition": {"target_metrics": list(dict.fromkeys(target_metrics))},
                "heuristic": text.strip(),
                "priority": priority,
                "scope": scope,
            }
        )
    normalized = [dict(item) for item in _deduplicate_heuristics(normalized)]
    if len(normalized) < 3:
        raise ValueError("critical heuristic extraction requires at least 3 unique heuristics")
    return normalized


def write_case_and_rebuild_global_heuristics(
    *, case_name: str, heuristics: Sequence[Mapping[str, Any]], base_dir: str | Path | None = None
) -> dict[str, str]:
    case_path = critical_heuristics_path(case_name, base_dir=base_dir)
    case_path.parent.mkdir(parents=True, exist_ok=True)
    case_path.write_text(
        json.dumps(list(heuristics), indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    all_items: list[Mapping[str, Any]] = []
    for path in sorted(case_path.parent.glob("*_critical_heuristics.json")):
        if path.name == "global_critical_heuristics.json":
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, list):
            all_items.extend(item for item in value if isinstance(item, Mapping))
    global_path = critical_heuristics_path("global", base_dir=case_path.parent)
    global_items = _deduplicate_heuristics(all_items)
    global_path.write_text(
        json.dumps(global_items, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return {"case": str(case_path), "global": str(global_path)}


def load_critical_heuristics(
    *,
    case_name: str,
    base_dir: str | Path | None = None,
) -> List[Mapping[str, Any]]:
    path = critical_heuristics_path(case_name, base_dir=base_dir)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        heuristics = payload.get("heuristics")
        if isinstance(heuristics, Sequence) and not isinstance(heuristics, (str, bytes)):
            return [item for item in heuristics if isinstance(item, Mapping)]
    return []


def _condition_matches(condition: Any, *, target_metrics: set[str]) -> bool:
    if condition is None:
        return True
    if not isinstance(condition, Mapping):
        return False

    condition_target_metrics = condition.get("target_metrics")
    if condition_target_metrics is not None:
        if not isinstance(condition_target_metrics, Sequence) or isinstance(
            condition_target_metrics, (str, bytes)
        ):
            return False
        allowed = normalize_metric_set(
            [
                str(item)
                for item in condition_target_metrics
                if isinstance(item, str) and item.strip()
            ]
        )
        if not target_metrics.intersection(allowed):
            return False

    return True


def _scope_matches(item_scope: Any, *, scope: str | None) -> bool:
    if scope is None or not scope.strip():
        return True
    requested = scope.strip().lower()
    if not isinstance(item_scope, str) or not item_scope.strip():
        return True
    normalized = item_scope.strip().lower()
    return normalized == "both" or normalized == requested


def _deduplicate_heuristics(items: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    selected: dict[tuple[str, tuple[str, ...], str], Mapping[str, Any]] = {}
    for item in items:
        text = item.get("heuristic")
        if not isinstance(text, str) or not text.strip():
            continue
        condition = item.get("condition")
        metrics = condition.get("target_metrics", []) if isinstance(condition, Mapping) else []
        metric_key = tuple(sorted(str(metric) for metric in metrics if isinstance(metric, str)))
        key = (" ".join(text.lower().split()), metric_key, str(item.get("scope", "")))
        current = selected.get(key)
        if current is None or _PRIORITY_RANK.get(
            str(item.get("priority")), 99
        ) < _PRIORITY_RANK.get(str(current.get("priority")), 99):
            selected[key] = item
    return list(selected.values())
