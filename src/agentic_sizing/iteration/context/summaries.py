from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from .data import (
    compute_weighted_violations,
    evaluate_unsatisfied_metrics,
    extract_performance_specs,
    map_parameter_vector,
    map_performance_vector,
)
from .errors import IterativeSizingContextError

SYNTHETIC_CONTROL_ROLE = "Testbench and bias controls"


def build_planner_local_summary(
    *,
    working_performances: Mapping[str, float],
    unsatisfied_metrics: Sequence[Mapping[str, Any]],
    recent_records: Sequence[Mapping[str, Any]],
    recent_role_metric_selections: Sequence[Mapping[str, Any]],
    role_perf_facts: Sequence[Mapping[str, Any]],
    perf_tradeoff_facts: Sequence[Mapping[str, Any]],
    outputs_spec: Mapping[str, Any],
    anchor_status: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    phase = _estimate_phase(unsatisfied_metrics, recent_records, outputs_spec)
    priority_metrics = sorted(
        [dict(item) for item in unsatisfied_metrics if isinstance(item, Mapping)],
        key=lambda item: float(item.get("gap", 0.0) or 0.0),
        reverse=True,
    )
    recent_role_focus = _summarize_recent_role_focus(recent_role_metric_selections)
    role_priority_hints = _build_role_priority_hints(role_perf_facts)
    tradeoff_alerts = _build_tradeoff_alerts(perf_tradeoff_facts)
    metric_names = [
        str(item.get("name")) for item in priority_metrics[:4] if isinstance(item.get("name"), str)
    ]

    return {
        "phase": phase,
        "unsatisfied_metric_count": len(priority_metrics),
        "priority_metrics": priority_metrics[:4],
        "recent_metric_trends": _summarize_metric_trends(
            metric_names,
            recent_records,
            outputs_spec,
        ),
        "recent_role_focus": recent_role_focus,
        "stalled_role_metric_pairs": [
            item for item in recent_role_focus if int(item.get("selection_count", 0)) >= 2
        ],
        "anchor_status": _normalize_anchor_status(anchor_status),
        "role_priority_hints": role_priority_hints,
        "tradeoff_alerts": tradeoff_alerts[:4],
    }


def build_worker_local_summary(
    *,
    role_name: str,
    target_metric: str,
    role_variables: Sequence[str],
    working_design: Mapping[str, float],
    working_performances: Mapping[str, float],
    recent_records: Sequence[Mapping[str, Any]],
    design_specs_json: Any,
    outputs_spec: Mapping[str, Any],
    anchor_status: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    unsatisfied_metrics = evaluate_unsatisfied_metrics(working_performances, design_specs_json)
    phase = _estimate_phase(unsatisfied_metrics, recent_records, outputs_spec)
    role_moves = _summarize_recent_role_moves(
        role_variables=role_variables,
        target_metric=target_metric,
        recent_records=recent_records,
        outputs_spec=outputs_spec,
    )
    variable_signals = _summarize_role_variable_signals(role_moves)
    target_tradeoff_metrics = _summarize_target_tradeoff_metrics(
        target_metric=target_metric,
        recent_records=recent_records,
        design_specs_json=design_specs_json,
    )
    oscillation_alerts = _summarize_role_move_oscillation(role_moves)

    return {
        "phase": phase,
        "role_name": role_name,
        "anchor_status": _normalize_anchor_status(anchor_status),
        "role_variable_signals": variable_signals[:3],
        "target_tradeoff_metrics": target_tradeoff_metrics,
        "oscillation_alerts": oscillation_alerts,
    }


def _normalize_anchor_status(anchor_status: Mapping[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(anchor_status, Mapping):
        return {
            "action": "unknown",
            "reverted": False,
            "best_known_iteration": None,
            "latest_record_iter": None,
            "message": "",
            "allowed_recovery_actions": ["continue_current"],
        }
    normalized = {
        "action": str(anchor_status.get("action", "unknown")),
        "reverted": bool(anchor_status.get("reverted", False)),
        "best_known_iteration": anchor_status.get("best_known_iteration"),
        "latest_record_iter": anchor_status.get("latest_record_iter"),
        "message": str(anchor_status.get("message", "")),
    }
    allowed_actions = anchor_status.get("allowed_recovery_actions")
    if isinstance(allowed_actions, list):
        normalized["allowed_recovery_actions"] = [
            str(item) for item in allowed_actions if isinstance(item, str)
        ]
    else:
        normalized["allowed_recovery_actions"] = ["continue_current"]
    for key in (
        "current_weighted_violation",
        "best_known_weighted_violation",
        "revert_guard_passed",
    ):
        if key in anchor_status:
            normalized[key] = anchor_status[key]
    return normalized


def _map_simulation_records(
    records: Sequence[Mapping[str, Any]],
    design_var_order: Sequence[str],
    perf_order: Sequence[str],
) -> List[Dict[str, Any]]:
    mapped: List[Dict[str, Any]] = []
    for record in records:
        parameters = record.get("parameters")
        performance = record.get("performance")
        if not isinstance(parameters, list) or not isinstance(performance, list):
            continue
        mapped.append(
            {
                "iter": int(record.get("iter", 0)),
                "design_vars": map_parameter_vector(parameters, design_var_order),
                "performances": map_performance_vector(performance, perf_order),
            }
        )
    return mapped


def _filter_design_vars_for_role(
    design_vars: Mapping[str, Any],
    role_variables: Sequence[str],
) -> Dict[str, float]:
    allowed = {name for name in role_variables if isinstance(name, str) and name.strip()}
    return {
        name: float(value)
        for name, value in design_vars.items()
        if name in allowed and isinstance(value, (int, float))
    }


def _filter_improving_design_samples(
    samples: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    role_variables: Sequence[str],
    target_metric: str,
) -> Dict[str, List[Dict[str, Any]]]:
    filtered: Dict[str, List[Dict[str, Any]]] = {}
    for group_name in ("latest", "best"):
        group = samples.get(group_name, [])
        normalized_group: List[Dict[str, Any]] = []
        for item in group:
            if not isinstance(item, Mapping):
                continue
            normalized_group.append(
                _compress_improving_design_sample(
                    item,
                    role_variables=role_variables,
                    target_metric=target_metric,
                )
            )
        filtered[group_name] = normalized_group
    return filtered


def _compress_latest_results(
    records: Sequence[Mapping[str, Any]],
    *,
    role_variables: Sequence[str],
) -> List[Dict[str, Any]]:
    compressed: List[Dict[str, Any]] = []
    for record in records:
        design_vars = record.get("design_vars")
        performances = record.get("performances")
        if not isinstance(design_vars, Mapping) or not isinstance(performances, Mapping):
            continue
        compressed.append(
            {
                "iter": int(record.get("iter", 0)),
                "design_vars": _filter_design_vars_for_role(design_vars, role_variables),
                "performances": {
                    str(name): float(value)
                    for name, value in performances.items()
                    if isinstance(name, str) and isinstance(value, (int, float))
                },
            }
        )
    return compressed


def _estimate_phase(
    unsatisfied_metrics: Sequence[Mapping[str, Any]],
    recent_records: Sequence[Mapping[str, Any]],
    outputs_spec: Mapping[str, Any],
) -> str:
    unsatisfied_count = len(list(unsatisfied_metrics))
    if unsatisfied_count <= 0:
        return "satisfied"
    if unsatisfied_count >= 2:
        return "feasibility"

    violation_series: List[float] = []
    for record in recent_records:
        perfs = record.get("performances")
        if isinstance(perfs, Mapping):
            violation_series.append(compute_weighted_violations(perfs, outputs_spec))

    if len(violation_series) >= 2 and violation_series[-1] < violation_series[0] * 0.9:
        return "tradeoff_shaping"
    return "fine_tuning"


def _compress_improving_design_sample(
    item: Mapping[str, Any],
    *,
    role_variables: Sequence[str],
    target_metric: str,
) -> Dict[str, Any]:
    before_design = _filter_design_vars_for_role(item.get("before_design_vars", {}), role_variables)
    after_design = _filter_design_vars_for_role(item.get("after_design_vars", {}), role_variables)
    before_perfs = (
        dict(item.get("before_performances", {}))
        if isinstance(item.get("before_performances"), Mapping)
        else {}
    )
    after_perfs = (
        dict(item.get("after_performances", {}))
        if isinstance(item.get("after_performances"), Mapping)
        else {}
    )

    return {
        "iters": [int(item.get("before_iter", 0)), int(item.get("after_iter", 0))],
        "var_changes": _summarize_variable_changes(before_design, after_design),
        "metric_changes": _summarize_metric_changes(
            before_perfs, after_perfs, target_metric=target_metric
        ),
    }


def _summarize_variable_changes(
    before_design: Mapping[str, float],
    after_design: Mapping[str, float],
    *,
    max_items: int = 4,
) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    names = sorted(set(before_design.keys()) | set(after_design.keys()))
    for name in names:
        before = before_design.get(name)
        after = after_design.get(name)
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            continue
        if abs(float(after) - float(before)) <= _value_tolerance(float(before)):
            continue
        changes.append(
            {
                "name": name,
                "from": _round_compact_number(before),
                "to": _round_compact_number(after),
            }
        )
    changes.sort(key=lambda item: str(item.get("name", "")))
    return changes[: max(0, max_items)]


def _summarize_metric_changes(
    before_perfs: Mapping[str, Any],
    after_perfs: Mapping[str, Any],
    *,
    target_metric: str,
    max_items: int = 4,
) -> List[Dict[str, Any]]:
    selected: List[str] = []
    if target_metric in before_perfs and target_metric in after_perfs:
        selected.append(target_metric)

    candidates: List[tuple[float, str]] = []
    for name in sorted(set(before_perfs.keys()) | set(after_perfs.keys())):
        if name == target_metric:
            continue
        before = before_perfs.get(name)
        after = after_perfs.get(name)
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            continue
        delta = abs(float(after) - float(before))
        if delta <= _value_tolerance(float(before)):
            continue
        candidates.append((delta, name))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    selected.extend(name for _, name in candidates[: max(0, max_items - len(selected))])

    result: List[Dict[str, Any]] = []
    for name in selected:
        before = before_perfs.get(name)
        after = after_perfs.get(name)
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            continue
        result.append(
            {
                "name": name,
                "from": _round_compact_number(before),
                "to": _round_compact_number(after),
            }
        )
    return result


def _round_compact_number(value: Any) -> float | int | Any:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value == 0.0:
            return 0.0
        return float(f"{value:.4g}")
    return value


def _summarize_metric_trends(
    metric_names: Sequence[str],
    recent_records: Sequence[Mapping[str, Any]],
    outputs_spec: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for metric in metric_names:
        values: List[float] = []
        for record in recent_records:
            perfs = record.get("performances")
            if isinstance(perfs, Mapping) and isinstance(perfs.get(metric), (int, float)):
                values.append(float(perfs[metric]))
        if not values:
            continue
        method = _metric_method(metric, outputs_spec)
        summaries.append(
            {
                "name": metric,
                "latest": values[-1],
                "delta_last": float(values[-1] - values[-2]) if len(values) >= 2 else 0.0,
                "trend": _classify_metric_trend(values, method),
            }
        )
    return summaries


def _summarize_recent_role_focus(
    recent_role_metric_selections: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    aggregated: Dict[tuple[str, str], int] = {}
    for item in recent_role_metric_selections:
        role_name = str(item.get("selected_role_name", "")).strip()
        target_metric = str(item.get("target_metric", "")).strip()
        if not role_name or not target_metric:
            continue
        key = (role_name, target_metric)
        aggregated[key] = aggregated.get(key, 0) + 1

    summaries = [
        {
            "role_name": role_name,
            "target_metric": target_metric,
            "selection_count": count,
        }
        for (role_name, target_metric), count in aggregated.items()
    ]
    summaries.sort(
        key=lambda item: (-int(item["selection_count"]), item["role_name"], item["target_metric"])
    )
    return summaries[:5]


def _build_role_priority_hints(
    role_perf_facts: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    influence_rank = {"dominant": 0, "significant": 1, "weak": 2}
    metric_map: Dict[str, List[Dict[str, Any]]] = {}
    for fact in role_perf_facts:
        metric = fact.get("metric")
        role = fact.get("functional_role")
        influence = fact.get("influence")
        confidence = fact.get("confidence")
        if (
            not isinstance(metric, str)
            or not isinstance(role, str)
            or not isinstance(influence, str)
        ):
            continue
        metric_map.setdefault(metric, []).append(
            {
                "role_name": role,
                "influence": influence,
                "confidence": float(confidence) if isinstance(confidence, (int, float)) else 0.0,
            }
        )

    hints: List[Dict[str, Any]] = []
    for metric, entries in metric_map.items():
        dedup: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            existing = dedup.get(entry["role_name"])
            if existing is None or (
                influence_rank.get(entry["influence"], 9),
                -entry["confidence"],
            ) < (influence_rank.get(existing["influence"], 9), -existing["confidence"]):
                dedup[entry["role_name"]] = entry
        ordered = sorted(
            dedup.values(),
            key=lambda item: (
                influence_rank.get(item["influence"], 9),
                -float(item["confidence"]),
                item["role_name"],
            ),
        )
        hints.append({"metric": metric, "ordered_roles": ordered})

    hints.sort(key=lambda item: item["metric"])
    return hints[:4]


def _build_tradeoff_alerts(perf_tradeoff_facts: Sequence[Mapping[str, Any]]) -> List[str]:
    alerts: List[str] = []
    seen: set[str] = set()
    for fact in perf_tradeoff_facts:
        subject = fact.get("subject")
        obj = fact.get("object")
        if not isinstance(subject, str) or not isinstance(obj, str):
            continue
        message = f"{subject} is coupled with {obj}; direction intentionally unspecified"
        if message not in seen:
            seen.add(message)
            alerts.append(message)
    return alerts


def _find_metric_spec(metric_name: str, design_specs_json: Any) -> Dict[str, Any]:
    for item in extract_performance_specs(design_specs_json):
        if item["name"] == metric_name:
            return item
    raise IterativeSizingContextError(f"Metric '{metric_name}' not found in design specs")


def _objective_metric_name(design_specs_json: Any) -> str:
    if not isinstance(design_specs_json, Mapping):
        return ""
    objective = design_specs_json.get("objective")
    if not isinstance(objective, Mapping):
        return ""
    metric = objective.get("metric")
    return metric if isinstance(metric, str) else ""


def _build_metric_status(
    metric_name: str,
    performances: Mapping[str, float],
    metric_spec: Mapping[str, Any],
) -> Dict[str, Any]:
    current = performances.get(metric_name)
    method = str(metric_spec["method"])
    threshold = float(metric_spec["threshold"])
    status = {
        "name": metric_name,
        "method": method,
        "threshold": threshold,
        "current": float(current) if isinstance(current, (int, float)) else None,
        "gap": None,
        "satisfied": False,
    }
    if not isinstance(current, (int, float)):
        return status
    current_value = float(current)
    if method == "min":
        gap = max(0.0, threshold - current_value)
        status["satisfied"] = current_value >= threshold
    elif method == "max":
        gap = max(0.0, current_value - threshold)
        status["satisfied"] = current_value <= threshold
    else:
        tolerance = max(abs(threshold) * 0.01, 1e-6)
        gap = max(current_value - threshold, 0.0)
        status["satisfied"] = (current_value - threshold) <= tolerance
    status["gap"] = float(gap)
    return status


def _summarize_recent_role_moves(
    *,
    role_variables: Sequence[str],
    target_metric: str,
    recent_records: Sequence[Mapping[str, Any]],
    outputs_spec: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    if len(recent_records) < 2:
        return []

    transitions: List[Dict[str, Any]] = []
    target_method = _metric_method(target_metric, outputs_spec)
    for previous, current in zip(recent_records[:-1], recent_records[1:]):
        prev_design = previous.get("design_vars")
        curr_design = current.get("design_vars")
        prev_perfs = previous.get("performances")
        curr_perfs = current.get("performances")
        if not isinstance(prev_design, Mapping) or not isinstance(curr_design, Mapping):
            continue
        if not isinstance(prev_perfs, Mapping) or not isinstance(curr_perfs, Mapping):
            continue

        changed_variables: List[Dict[str, Any]] = []
        for name in role_variables:
            if not isinstance(prev_design.get(name), (int, float)) or not isinstance(
                curr_design.get(name), (int, float)
            ):
                continue
            delta = float(curr_design[name]) - float(prev_design[name])
            if abs(delta) <= _value_tolerance(float(prev_design[name])):
                continue
            changed_variables.append(
                {
                    "name": name,
                    "delta": delta,
                    "direction": "increase" if delta > 0 else "decrease",
                }
            )

        if not changed_variables:
            continue

        prev_target = prev_perfs.get(target_metric)
        curr_target = curr_perfs.get(target_metric)
        if isinstance(prev_target, (int, float)) and isinstance(curr_target, (int, float)):
            target_delta = float(curr_target) - float(prev_target)
            target_effect = _classify_metric_delta(target_delta, target_method)
        else:
            target_delta = 0.0
            target_effect = "unknown"

        transitions.append(
            {
                "from_iter": int(previous.get("iter", 0)),
                "to_iter": int(current.get("iter", 0)),
                "changed_variables": changed_variables,
                "target_metric_delta": target_delta,
                "target_metric_effect": target_effect,
                "violation_delta": float(
                    compute_weighted_violations(curr_perfs, outputs_spec)
                    - compute_weighted_violations(prev_perfs, outputs_spec)
                ),
            }
        )

    return list(reversed(transitions))


def _summarize_role_variable_signals(
    role_moves: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    stats: Dict[str, Dict[str, int]] = {}
    for move in role_moves:
        effect = str(move.get("target_metric_effect", "unknown"))
        changed = move.get("changed_variables")
        if not isinstance(changed, list):
            continue
        for item in changed:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name")
            direction = item.get("direction")
            if not isinstance(name, str) or not isinstance(direction, str):
                continue
            key = f"{direction}_{effect}"
            stats.setdefault(name, {})[key] = stats.setdefault(name, {}).get(key, 0) + 1

    summaries: List[Dict[str, Any]] = []
    for name, counts in stats.items():
        candidates = [
            ("increase_improves_recently", counts.get("increase_improved", 0)),
            ("decrease_improves_recently", counts.get("decrease_improved", 0)),
            ("increase_degrades_recently", counts.get("increase_degraded", 0)),
            ("decrease_degrades_recently", counts.get("decrease_degraded", 0)),
        ]
        signal, strength = max(candidates, key=lambda item: item[1])
        if strength <= 0:
            signal = "insufficient_data"
        summaries.append(
            {
                "name": name,
                "signal": signal,
                "counts": counts,
                "summary": _format_variable_signal_summary(name, signal, counts),
            }
        )

    summaries.sort(key=lambda item: (item["signal"].startswith("insufficient"), item["name"]))
    return summaries


def _format_variable_signal_summary(name: str, signal: str, counts: Mapping[str, int]) -> str:
    if signal == "increase_improves_recently":
        return f"Increasing {name} has helped recently in local committed moves."
    if signal == "decrease_improves_recently":
        return f"Decreasing {name} has helped recently in local committed moves."
    if signal == "increase_degrades_recently":
        return f"Increasing {name} has degraded the target recently in local committed moves."
    if signal == "decrease_degrades_recently":
        return f"Decreasing {name} has degraded the target recently in local committed moves."
    return f"{name} has insufficient local move history for a clear signal."


def _summarize_recent_reopened_metrics(
    recent_records: Sequence[Mapping[str, Any]],
    design_specs_json: Any,
) -> List[Dict[str, Any]]:
    if len(recent_records) < 2:
        return []

    specs = extract_performance_specs(design_specs_json)
    reopen_counts: Dict[str, int] = {}
    last_transition: Dict[str, Dict[str, int]] = {}

    for previous, current in zip(recent_records[:-1], recent_records[1:]):
        prev_perfs = previous.get("performances")
        curr_perfs = current.get("performances")
        if not isinstance(prev_perfs, Mapping) or not isinstance(curr_perfs, Mapping):
            continue

        for spec in specs:
            prev_status = _build_metric_status(spec["name"], prev_perfs, spec)
            curr_status = _build_metric_status(spec["name"], curr_perfs, spec)
            if bool(prev_status.get("satisfied")) and not bool(curr_status.get("satisfied")):
                name = spec["name"]
                reopen_counts[name] = reopen_counts.get(name, 0) + 1
                last_transition[name] = {
                    "from_iter": int(previous.get("iter", 0)),
                    "to_iter": int(current.get("iter", 0)),
                }

    summaries = [
        {
            "name": name,
            "reopen_count": count,
            "last_reopened_from_iter": last_transition.get(name, {}).get("from_iter", 0),
            "last_reopened_to_iter": last_transition.get(name, {}).get("to_iter", 0),
        }
        for name, count in reopen_counts.items()
    ]
    summaries.sort(key=lambda item: (-int(item["reopen_count"]), item["name"]))
    return summaries[:4]


def _summarize_target_tradeoff_metrics(
    *,
    target_metric: str,
    recent_records: Sequence[Mapping[str, Any]],
    design_specs_json: Any,
) -> List[Dict[str, Any]]:
    if len(recent_records) < 2:
        return []

    specs = extract_performance_specs(design_specs_json)
    spec_by_name = {str(spec["name"]): spec for spec in specs}
    target_spec = spec_by_name.get(target_metric)
    if target_spec is None:
        return []

    tradeoff_counts: Dict[str, int] = {}
    last_transition: Dict[str, Dict[str, int]] = {}

    for previous, current in zip(recent_records[:-1], recent_records[1:]):
        prev_perfs = previous.get("performances")
        curr_perfs = current.get("performances")
        if not isinstance(prev_perfs, Mapping) or not isinstance(curr_perfs, Mapping):
            continue

        prev_target = prev_perfs.get(target_metric)
        curr_target = curr_perfs.get(target_metric)
        if not isinstance(prev_target, (int, float)) or not isinstance(curr_target, (int, float)):
            continue

        target_effect = _classify_metric_delta(
            float(curr_target) - float(prev_target), str(target_spec["method"])
        )
        if target_effect != "improved":
            continue

        for spec_name, spec in spec_by_name.items():
            if spec_name == target_metric:
                continue
            prev_status = _build_metric_status(spec_name, prev_perfs, spec)
            curr_status = _build_metric_status(spec_name, curr_perfs, spec)
            prev_gap = prev_status.get("gap")
            curr_gap = curr_status.get("gap")
            if not isinstance(prev_gap, (int, float)) or not isinstance(curr_gap, (int, float)):
                continue
            worsened = float(curr_gap) > float(prev_gap) + _value_tolerance(float(prev_gap))
            reopened = bool(prev_status.get("satisfied")) and not bool(curr_status.get("satisfied"))
            if worsened or reopened:
                tradeoff_counts[spec_name] = tradeoff_counts.get(spec_name, 0) + 1
                last_transition[spec_name] = {
                    "from_iter": int(previous.get("iter", 0)),
                    "to_iter": int(current.get("iter", 0)),
                    "reopened": 1 if reopened else 0,
                }

    summaries = [
        {
            "name": name,
            "conflict_count": count,
            "last_conflict_from_iter": last_transition.get(name, {}).get("from_iter", 0),
            "last_conflict_to_iter": last_transition.get(name, {}).get("to_iter", 0),
            "recently_reopened": bool(last_transition.get(name, {}).get("reopened", 0)),
        }
        for name, count in tradeoff_counts.items()
    ]
    summaries.sort(key=lambda item: (-int(item["conflict_count"]), item["name"]))
    return summaries[:4]


def _summarize_role_move_oscillation(role_moves: Sequence[Mapping[str, Any]]) -> List[str]:
    if len(role_moves) < 2:
        return []

    chronological_moves = list(reversed([move for move in role_moves if isinstance(move, Mapping)]))
    alerts: List[str] = []
    seen: set[str] = set()

    for previous, current in zip(chronological_moves[:-1], chronological_moves[1:]):
        prev_changed = previous.get("changed_variables")
        curr_changed = current.get("changed_variables")
        if not isinstance(prev_changed, list) or not isinstance(curr_changed, list):
            continue
        prev_directions = {
            str(item.get("name")): str(item.get("direction"))
            for item in prev_changed
            if isinstance(item, Mapping)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("direction"), str)
        }
        curr_directions = {
            str(item.get("name")): str(item.get("direction"))
            for item in curr_changed
            if isinstance(item, Mapping)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("direction"), str)
        }

        for name, prev_direction in prev_directions.items():
            curr_direction = curr_directions.get(name)
            if curr_direction and curr_direction != prev_direction:
                message = (
                    f"{name} was reversed across recent role moves "
                    f"({previous.get('from_iter', 0)}->{previous.get('to_iter', 0)} then "
                    f"{current.get('from_iter', 0)}->{current.get('to_iter', 0)})."
                )
                if message not in seen:
                    seen.add(message)
                    alerts.append(message)

    return alerts[:4]


def _metric_method(metric_name: str, outputs_spec: Mapping[str, Any]) -> str:
    spec = outputs_spec.get(metric_name) if isinstance(outputs_spec, Mapping) else None
    if isinstance(spec, list) and len(spec) >= 2 and isinstance(spec[1], str):
        return spec[1]
    return "target"


def _classify_metric_trend(values: Sequence[float], method: str) -> str:
    if len(values) < 2:
        return "insufficient_data"
    delta = float(values[-1]) - float(values[0])
    return _classify_metric_delta(delta, method)


def _classify_metric_delta(delta: float, method: str) -> str:
    tolerance = _value_tolerance(delta)
    if abs(delta) <= tolerance:
        return "flat"
    if method == "max":
        return "improved" if delta < 0 else "degraded"
    return "improved" if delta > 0 else "degraded"


def _value_tolerance(value: float) -> float:
    return max(abs(float(value)) * 1e-6, 1e-12)
