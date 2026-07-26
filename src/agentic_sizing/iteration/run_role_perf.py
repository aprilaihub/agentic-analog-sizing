from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..core.models import FunctionalRole


def get_run_role_perf_path(simulation_record_path: str) -> Path:
    record_path = Path(simulation_record_path).expanduser().resolve()
    return record_path.with_name(f"{record_path.stem}_run_role_perf.json")


def remove_run_role_perf_summary(simulation_record_path: str) -> None:
    path = get_run_role_perf_path(simulation_record_path)
    if path.exists():
        path.unlink()


def update_run_role_perf_summary(
    *,
    simulation_record_path: str,
    role: FunctionalRole | None,
    metric: str,
    before_perfs: Mapping[str, Any],
    after_perfs: Mapping[str, Any],
    specs: list[Any],
    iteration: int,
) -> None:
    role_name = getattr(role, "role_name", "") if role is not None else ""
    metric_name = str(metric or "").strip()
    if not role_name or not metric_name:
        return

    before_gap = _metric_gap(metric_name, before_perfs, specs)
    after_gap = _metric_gap(metric_name, after_perfs, specs)
    if before_gap is None or after_gap is None:
        return

    improvement = before_gap - after_gap
    if abs(improvement) <= _tolerance(before_gap, after_gap):
        influence = "weak"
        confidence_delta = 0.0
    elif improvement > 0:
        influence = "significant"
        confidence_delta = 0.08
    else:
        influence = "weak"
        confidence_delta = -0.04

    path = get_run_role_perf_path(simulation_record_path)
    payload = _load_payload(path)
    facts = payload.setdefault("facts", [])
    fact = _find_fact(facts, role_name, metric_name)
    if fact is None:
        fact = {
            "type": "role_perf",
            "functional_role": role_name,
            "metric": metric_name,
            "influence": influence,
            "confidence": 0.55,
            "evidence_count": 0,
            "evidence_iters": [],
            "topology": "run_local",
            "note": "Ephemeral run-local role/metric signal from committed simulation outcomes.",
        }
        facts.append(fact)

    fact["evidence_count"] = int(fact.get("evidence_count", 0) or 0) + 1
    fact["evidence_iters"] = [*list(fact.get("evidence_iters", []) or []), int(iteration)][-12:]
    fact["last_before_gap"] = before_gap
    fact["last_after_gap"] = after_gap
    fact["last_gap_delta"] = improvement
    fact["confidence"] = _clamp_confidence(float(fact.get("confidence", 0.55)) + confidence_delta)
    fact["influence"] = _stronger_influence(str(fact.get("influence", "weak")), influence)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"facts": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"facts": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("facts"), list):
        return {"facts": []}
    return payload


def _find_fact(facts: list[Any], role_name: str, metric_name: str) -> dict[str, Any] | None:
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if fact.get("functional_role") == role_name and fact.get("metric") == metric_name:
            return fact
    return None


def _metric_gap(metric: str, perfs: Mapping[str, Any], specs: list[Any]) -> float | None:
    if metric not in perfs:
        return None
    value = perfs.get(metric)
    if not isinstance(value, (int, float)):
        return None

    spec = next((item for item in specs if getattr(item, "name", "") == metric), None)
    if spec is None:
        return None

    target = float(getattr(spec, "target"))
    relation = str(getattr(spec, "relation"))
    numeric_value = float(value)
    if relation == "min":
        return max(target - numeric_value, 0.0)
    if relation in {"max", "target"}:
        return max(numeric_value - target, 0.0)
    return abs(numeric_value - target)


def _stronger_influence(current: str, candidate: str) -> str:
    rank = {"weak": 0, "significant": 1, "dominant": 2}
    return candidate if rank.get(candidate, 0) > rank.get(current, 0) else current


def _clamp_confidence(value: float) -> float:
    return min(0.95, max(0.2, value))


def _tolerance(*values: float) -> float:
    scale = max([1.0, *[abs(float(value)) for value in values]])
    return scale * 1e-9
