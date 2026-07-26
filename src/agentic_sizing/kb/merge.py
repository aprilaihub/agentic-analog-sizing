from __future__ import annotations

import glob
import json
import os
from typing import Any, Dict, List, Literal, Tuple

from .schemas import normalize_direction, normalize_parameter_name

Fact = Dict[str, Any]


def merge_kb_files(
    input_paths: List[str],
    omit_conflicts: bool = True,
    same_fact_policy: Literal["merge_strengthen", "keep_duplicates"] = "merge_strengthen",
) -> List[Fact]:
    """Merge multiple KB files into a single fact list.

    Parameters
    ----------
    input_paths
        File paths or glob patterns.
    omit_conflicts
        If True, removes fact families containing opposite influence variants. Directional
        variants are normalized to ``unspecified`` and retained as one critical/coupled fact.
    same_fact_policy
        - "merge_strengthen": merge same-key facts and strengthen evidence/confidence.
        - "keep_duplicates": keep same-key/same-direction duplicates as independent facts.
    """

    expanded_paths: List[str] = []
    for path in input_paths:
        matches = glob.glob(path)
        if matches:
            expanded_paths.extend(matches)
        elif os.path.exists(path):
            expanded_paths.append(path)

    if not expanded_paths:
        return []

    all_facts: List[Fact] = []
    for path in expanded_paths:
        all_facts.extend(_load_facts_from_path(path))

    return merge_fact_lists(
        existing_facts=[],
        new_facts=all_facts,
        omit_conflicts=omit_conflicts,
        same_fact_policy=same_fact_policy,
    )


def merge_fact_lists(
    existing_facts: List[Fact],
    new_facts: List[Fact],
    omit_conflicts: bool = True,
    same_fact_policy: Literal["merge_strengthen", "keep_duplicates"] = "merge_strengthen",
) -> List[Fact]:
    """Merge two fact lists with configurable same-fact behavior."""

    if same_fact_policy not in {"merge_strengthen", "keep_duplicates"}:
        raise ValueError(
            "same_fact_policy must be 'merge_strengthen' or 'keep_duplicates', "
            f"got: {same_fact_policy}"
        )

    all_facts = [*existing_facts, *new_facts]
    if not all_facts:
        return []

    if same_fact_policy == "merge_strengthen":
        merged_by_key: Dict[Tuple[Any, ...], Fact] = {}
        for fact in all_facts:
            normalized = _seed_topology_provenance(_normalize_fact(fact))
            key = _full_key(normalized)
            if key in merged_by_key:
                merged_by_key[key] = _merge_two_facts(merged_by_key[key], normalized)
            else:
                merged_by_key[key] = normalized
        merged = list(merged_by_key.values())
    else:
        # keep_duplicates: preserve same-key same-direction facts as independent rows.
        merged = [_seed_topology_provenance(_normalize_fact(fact)) for fact in all_facts]

    if omit_conflicts:
        merged = _remove_conflicted_families(merged)

    merged = _infer_perf_tradeoff_facts(merged)

    if omit_conflicts:
        merged = _remove_conflicted_families(merged)

    # _finalize_topology_fields(merged)
    merged.sort(key=_sort_key)
    return merged


# ============================================================
# Loading
# ============================================================


def _load_facts_from_path(path: str) -> List[Fact]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return []

    try:
        obj = json.loads(content)

        if isinstance(obj, dict) and isinstance(obj.get("facts"), list):
            return [x for x in obj["facts"] if isinstance(x, dict)]

        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]

        if isinstance(obj, dict) and "type" in obj:
            return [obj]

    except json.JSONDecodeError:
        pass

    facts: List[Fact] = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                facts.append(obj)
        except json.JSONDecodeError:
            continue

    return facts


# ============================================================
# Merge Logic
# ============================================================


def _merge_two_facts(a: Fact, b: Fact) -> Fact:
    ea = int(a.get("evidence_count", 0))
    eb = int(b.get("evidence_count", 0))
    ca = float(a.get("confidence", 0.0))
    cb = float(b.get("confidence", 0.0))

    total_evidence = ea + eb
    new_conf = ((ca * ea + cb * eb) / total_evidence) if total_evidence > 0 else max(ca, cb)

    iters_a = set(a.get("evidence_iters", []) or [])
    iters_b = set(b.get("evidence_iters", []) or [])
    merged_iters = sorted(iters_a.union(iters_b))[:8]

    merged = dict(a)
    merged["evidence_count"] = total_evidence
    merged["confidence"] = float(new_conf)
    merged["evidence_iters"] = merged_iters

    tops_a = set(merged.get("topologies", []) or [])
    tops_b = set()
    topo_b = b.get("topology")
    if isinstance(topo_b, str) and topo_b:
        tops_b.add(topo_b)
    if isinstance(b.get("topologies"), list):
        tops_b.update([t for t in b["topologies"] if isinstance(t, str) and t])

    merged["topologies"] = sorted(tops_a.union(tops_b))
    return merged


def _normalize_fact(f: Fact) -> Fact:
    nf = dict(f)
    nf["evidence_count"] = int(nf.get("evidence_count", 0))
    nf["confidence"] = float(nf.get("confidence", 0.0))
    if nf.get("type") == "perf_perf_tradeoff":
        subject = nf.get("subject")
        obj = nf.get("object")
        if isinstance(subject, str) and isinstance(obj, str):
            canonical_subject, canonical_object = _canonical_perf_tradeoff_pair(subject, obj)
            nf["subject"] = canonical_subject
            nf["object"] = canonical_object
        if isinstance(nf.get("direction"), str):
            nf["direction"] = normalize_direction(nf["direction"])
    if nf.get("type") == "substruct_param_perf" and isinstance(nf.get("parameter"), str):
        nf["parameter"] = normalize_parameter_name(nf["parameter"])
        if isinstance(nf.get("direction"), str):
            nf["direction"] = normalize_direction(nf["direction"])

    iters = nf.get("evidence_iters", [])
    if isinstance(iters, list):
        out: List[int] = []
        for x in iters:
            if isinstance(x, int):
                out.append(x)
        nf["evidence_iters"] = sorted(set(out))[:8]
    else:
        nf["evidence_iters"] = []

    return nf


def _seed_topology_provenance(f: Fact) -> Fact:
    seeded = dict(f)
    tops = set()

    topo = seeded.get("topology")
    if isinstance(topo, str) and topo:
        tops.add(topo)

    existing = seeded.get("topologies")
    if isinstance(existing, list):
        tops.update([t for t in existing if isinstance(t, str) and t])

    seeded["topologies"] = sorted(tops)
    return seeded


def _canonical_perf_tradeoff_pair(subject: str, obj: str) -> Tuple[str, str]:
    ordered = sorted((subject, obj))
    return ordered[0], ordered[1]


def _infer_perf_tradeoff_facts(facts: List[Fact]) -> List[Fact]:
    positive_facts = [
        fact
        for fact in facts
        if fact.get("type") == "perf_perf_tradeoff" and fact.get("direction") == "positive"
    ]
    if len(positive_facts) < 2:
        return facts

    existing_pairs = {
        (str(fact.get("subject")), str(fact.get("object")))
        for fact in facts
        if fact.get("type") == "perf_perf_tradeoff"
    }

    inferred_by_pair: Dict[Tuple[str, str], Fact] = {}
    for first in positive_facts:
        first_subject = first.get("subject")
        first_object = first.get("object")
        if not isinstance(first_subject, str) or not isinstance(first_object, str):
            continue

        for second in positive_facts:
            if first is second:
                continue
            second_subject = second.get("subject")
            second_object = second.get("object")
            if not isinstance(second_subject, str) or not isinstance(second_object, str):
                continue

            shared_metric = _shared_positive_tradeoff_metric(
                first_subject,
                first_object,
                second_subject,
                second_object,
            )
            if shared_metric is None:
                continue

            inferred_endpoints = sorted(
                {
                    first_subject,
                    first_object,
                    second_subject,
                    second_object,
                }
                - {shared_metric}
            )
            if len(inferred_endpoints) != 2:
                continue

            pair = (inferred_endpoints[0], inferred_endpoints[1])
            if pair in existing_pairs:
                continue

            shared_topologies = sorted(
                set(_fact_topologies(first)).intersection(_fact_topologies(second))
            )
            if not shared_topologies:
                continue

            candidate = {
                "type": "perf_perf_tradeoff",
                "subject": pair[0],
                "relation": "trades_off_with",
                "object": pair[1],
                "direction": "positive",
                "confidence": max(
                    0.0,
                    min(float(first.get("confidence", 0.0)), float(second.get("confidence", 0.0)))
                    * 0.9,
                ),
                "evidence_count": min(
                    int(first.get("evidence_count", 0)),
                    int(second.get("evidence_count", 0)),
                ),
                "evidence_iters": sorted(
                    set(first.get("evidence_iters", []) or []).intersection(
                        second.get("evidence_iters", []) or []
                    )
                )[:8],
                "topology": shared_topologies[0],
                "topologies": shared_topologies,
            }

            existing = inferred_by_pair.get(pair)
            if existing is None or (
                float(candidate["confidence"]),
                int(candidate["evidence_count"]),
            ) > (
                float(existing.get("confidence", 0.0)),
                int(existing.get("evidence_count", 0)),
            ):
                inferred_by_pair[pair] = candidate

    if not inferred_by_pair:
        return facts

    return [*facts, *inferred_by_pair.values()]


def _shared_positive_tradeoff_metric(
    first_subject: str,
    first_object: str,
    second_subject: str,
    second_object: str,
) -> str | None:
    overlap = {first_subject, first_object}.intersection({second_subject, second_object})
    if len(overlap) != 1:
        return None
    return next(iter(overlap))


def _fact_topologies(fact: Fact) -> List[str]:
    tops = fact.get("topologies")
    if isinstance(tops, list):
        return [item for item in tops if isinstance(item, str) and item]
    topo = fact.get("topology")
    if isinstance(topo, str) and topo:
        return [topo]
    return []


def _finalize_topology_fields(facts: List[Fact]) -> None:
    for fact in facts:
        tops = fact.get("topologies", [])
        if isinstance(tops, list) and len(tops) == 1:
            fact["topology"] = tops[0]
        elif isinstance(tops, list) and len(tops) > 1:
            fact.pop("topology", None)


# ============================================================
# Conflict Handling
# ============================================================


def _remove_conflicted_families(facts: List[Fact]) -> List[Fact]:
    """Remove families containing opposite direction/influence variants."""

    family_map: Dict[Tuple[Any, ...], set] = {}
    for fact in facts:
        fam_key = _family_key_without_variant(fact)
        variant = (
            fact.get("direction"),
            fact.get("influence"),
        )
        family_map.setdefault(fam_key, set()).add(variant)

    conflicted_families = {fam for fam, variants in family_map.items() if len(variants) > 1}
    return [fact for fact in facts if _family_key_without_variant(fact) not in conflicted_families]


# ============================================================
# Key Definitions (Topology-agnostic)
# ============================================================


def _full_key(f: Fact) -> Tuple[Any, ...]:
    t = f.get("type")

    if t == "perf_perf_tradeoff":
        return (
            t,
            f.get("subject"),
            f.get("relation"),
            f.get("object"),
            f.get("direction"),
        )

    if t == "substruct_param_perf":
        return (
            t,
            f.get("substructure"),
            f.get("parameter"),
            f.get("metric"),
            f.get("direction"),
        )

    if t == "role_perf":
        return (
            t,
            f.get("functional_role"),
            f.get("metric"),
            f.get("influence"),
        )

    return (t, json.dumps(f, sort_keys=True))


def _family_key_without_variant(f: Fact) -> Tuple[Any, ...]:
    t = f.get("type")

    if t == "perf_perf_tradeoff":
        return (
            t,
            f.get("subject"),
            f.get("relation"),
            f.get("object"),
        )

    if t == "substruct_param_perf":
        return (
            t,
            f.get("substructure"),
            f.get("parameter"),
            f.get("metric"),
        )

    if t == "role_perf":
        return (
            t,
            f.get("functional_role"),
            f.get("metric"),
        )

    return (t,)


def _sort_key(f: Fact) -> Tuple[Any, ...]:
    tops = f.get("topologies", [])
    topo0 = tops[0] if isinstance(tops, list) and tops else ""
    return (
        topo0,
        f.get("type"),
        f.get("substructure"),
        f.get("parameter"),
        f.get("metric"),
        f.get("subject"),
        f.get("object"),
        f.get("functional_role"),
        f.get("direction"),
        f.get("influence"),
        f.get("evidence_count", 0),
    )
