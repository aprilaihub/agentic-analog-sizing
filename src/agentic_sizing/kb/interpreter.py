from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Sequence

from ..core.metric_aliases import canonical_metric_name, normalize_metric_set


def summarize_role_perf_facts(
    facts: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    target_metrics: Iterable[str] | None = None,
    allowed_roles: Iterable[str] | None = None,
    max_items: int = 6,
) -> List[str]:
    target_metric_set = normalize_metric_set(target_metrics)
    allowed_role_set = _normalize_name_set(allowed_roles)
    selected = []
    for fact in _extract_facts(facts):
        role = _as_text(fact.get("functional_role"))
        metric = _as_text(fact.get("metric"))
        influence = _as_text(fact.get("influence"))
        if not role or not metric or not influence:
            continue
        if target_metric_set and canonical_metric_name(metric) not in target_metric_set:
            continue
        if allowed_role_set and role not in allowed_role_set:
            continue
        selected.append(fact)

    ordered = _sort_facts(selected)[: max(0, max_items)]
    return [
        (
            f"{_as_text(fact.get('functional_role'))}: "
            f"{_as_text(fact.get('influence'))} influence on {_as_text(fact.get('metric'))} "
            f"(conf {_fact_confidence(fact):.2f}, n={_fact_evidence_count(fact)})."
        )
        for fact in ordered
    ]


def summarize_perf_tradeoff_facts(
    facts: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    target_metrics: Iterable[str] | None = None,
    max_items: int = 6,
) -> List[str]:
    target_metric_set = normalize_metric_set(target_metrics)
    selected = []
    for fact in _extract_facts(facts):
        subject = _as_text(fact.get("subject"))
        obj = _as_text(fact.get("object"))
        relation = _as_text(fact.get("relation"))
        if not subject or not obj or not relation:
            continue
        if (
            target_metric_set
            and canonical_metric_name(subject) not in target_metric_set
            and canonical_metric_name(obj) not in target_metric_set
        ):
            continue
        selected.append(fact)

    ordered = _sort_facts(selected)[: max(0, max_items)]
    return [
        (
            f"{_as_text(fact.get('subject'))} vs {_as_text(fact.get('object'))}: "
            "performance metrics are coupled; direction intentionally unspecified "
            f"(conf {_fact_confidence(fact):.2f}, n={_fact_evidence_count(fact)})."
        )
        for fact in ordered
    ]


def summarize_substruct_param_perf_facts(
    facts: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    target_metrics: Iterable[str] | None = None,
    max_items: int = 8,
) -> List[str]:
    target_metric_set = normalize_metric_set(target_metrics)
    selected = []
    for fact in _extract_facts(facts):
        substructure = _as_text(fact.get("substructure"))
        parameter = _as_text(fact.get("parameter"))
        metric = _as_text(fact.get("metric"))
        if not substructure or not parameter or not metric:
            continue
        if target_metric_set and canonical_metric_name(metric) not in target_metric_set:
            continue
        selected.append(fact)

    ordered = _sort_facts(selected)[: max(0, max_items)]
    return [
        (
            f"{_as_text(fact.get('substructure'))}.{_as_text(fact.get('parameter'))}: "
            f"is a critical parameter for {_as_text(fact.get('metric'))}; "
            "direction intentionally unspecified "
            f"(conf {_fact_confidence(fact):.2f})."
        )
        for fact in ordered
    ]


def _extract_facts(
    facts: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> List[Mapping[str, Any]]:
    if isinstance(facts, Mapping):
        payload = facts.get("facts")
        if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
            return [fact for fact in payload if isinstance(fact, Mapping)]
        return []
    if isinstance(facts, Sequence) and not isinstance(facts, (str, bytes)):
        return [fact for fact in facts if isinstance(fact, Mapping)]
    return []


def _normalize_name_set(values: Iterable[str] | None) -> set[str]:
    if values is None:
        return set()
    return {value for value in values if isinstance(value, str) and value.strip()}


def _as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _fact_confidence(fact: Mapping[str, Any]) -> float:
    value = fact.get("confidence")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _fact_evidence_count(fact: Mapping[str, Any]) -> int:
    value = fact.get("evidence_count")
    return int(value) if isinstance(value, (int, float)) else 0


def _sort_facts(facts: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return sorted(
        facts,
        key=lambda fact: (
            -_fact_confidence(fact),
            -_fact_evidence_count(fact),
            _as_text(fact.get("functional_role")),
            _as_text(fact.get("substructure")),
            _as_text(fact.get("parameter")),
            _as_text(fact.get("metric")),
            _as_text(fact.get("subject")),
            _as_text(fact.get("object")),
        ),
    )
