from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set


class KBFactsValidationError(ValueError):
    """Raised when KB fact payload does not satisfy expected constraints."""


VALID_DIRECTIONS = {
    "unspecified",
    "positive",
    "negative",
    "direct",
    "inverse",
    "increase_improves",
    "increase_degrades",
}

DIRECTION_NORMALIZATION = {
    "unspecified": "unspecified",
    "positive": "unspecified",
    "negative": "unspecified",
    "direct": "unspecified",
    "inverse": "unspecified",
    "increase_improves": "unspecified",
    "increase_degrades": "unspecified",
}

VALID_INFLUENCE = {"dominant", "significant", "weak"}


def load_kb_perf_tradeoff_schema() -> Dict[str, Any]:
    return _load_schema("kb_perf_tradeoff.schema.json")


def load_kb_substruct_param_perf_schema() -> Dict[str, Any]:
    return _load_schema("kb_substruct_param_perf.schema.json")


def load_kb_role_perf_schema() -> Dict[str, Any]:
    return _load_schema("kb_role_perf.schema.json")


def normalize_direction(value: str) -> str:
    normalized = DIRECTION_NORMALIZATION.get(value.strip())
    if normalized is None:
        raise KBFactsValidationError(
            "direction must be one of "
            "'unspecified', 'positive', 'negative', 'direct', 'inverse', "
            "'increase_improves', 'increase_degrades'."
        )
    return normalized


def normalize_parameter_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise KBFactsValidationError("parameter must be a non-empty string.")
    return re.sub(r"\d+$", "", stripped)


def validate_perf_tradeoff_payload(
    payload: Any,
    *,
    allowed_metrics: Set[str],
    topology: str,
) -> Dict[str, List[Dict[str, Any]]]:
    data = _require_payload(payload, context="kb_perf_tradeoff")
    facts = data["facts"]

    normalized_facts: List[Dict[str, Any]] = []
    for idx, fact in enumerate(facts):
        ctx = f"kb_perf_tradeoff.facts[{idx}]"
        obj = _require_dict(fact, ctx)
        _assert_keys(
            obj,
            [
                "type",
                "subject",
                "relation",
                "object",
                "direction",
                "confidence",
                "evidence_count",
                "evidence_iters",
                "topology",
            ],
            ctx,
            allowed_extras=["topologies"],
        )

        fact_type = _require_literal(obj.get("type"), f"{ctx}.type", {"perf_perf_tradeoff"})
        subject = _require_member(obj.get("subject"), f"{ctx}.subject", allowed_metrics)
        relation = _require_literal(obj.get("relation"), f"{ctx}.relation", {"trades_off_with"})
        obj_metric = _require_member(obj.get("object"), f"{ctx}.object", allowed_metrics)
        direction = normalize_direction(
            _require_literal(obj.get("direction"), f"{ctx}.direction", VALID_DIRECTIONS)
        )
        confidence = _require_confidence(obj.get("confidence"), f"{ctx}.confidence")
        evidence_count = _require_non_negative_int(
            obj.get("evidence_count"), f"{ctx}.evidence_count"
        )
        evidence_iters = _require_iters(obj.get("evidence_iters"), f"{ctx}.evidence_iters")
        # topology_name = _require_topology(obj.get("topology"), f"{ctx}.topology", topology)
        topologies = _require_topology_or_topologies(obj, ctx, topology)

        normalized_facts.append(
            {
                "type": fact_type,
                "subject": subject,
                "relation": relation,
                "object": obj_metric,
                "direction": direction,
                "confidence": confidence,
                "evidence_count": evidence_count,
                "evidence_iters": evidence_iters,
                "topology": topology,
                "topologies": topologies,
            }
        )

    return {"facts": normalized_facts}


def validate_substruct_param_perf_payload(
    payload: Any,
    *,
    allowed_substructures: Set[str],
    allowed_parameters: Set[str],
    allowed_metrics: Set[str],
    topology: str,
) -> Dict[str, List[Dict[str, Any]]]:
    data = _require_payload(payload, context="kb_substruct_param_perf")
    facts = data["facts"]

    normalized_facts: List[Dict[str, Any]] = []
    for idx, fact in enumerate(facts):
        ctx = f"kb_substruct_param_perf.facts[{idx}]"
        obj = _require_dict(fact, ctx)
        _assert_keys(
            obj,
            [
                "type",
                "substructure",
                "parameter",
                "metric",
                "direction",
                "confidence",
                "evidence_count",
                "evidence_iters",
                "topology",
            ],
            ctx,
            allowed_extras=["topologies"],
        )

        fact_type = _require_literal(obj.get("type"), f"{ctx}.type", {"substruct_param_perf"})
        substructure = _require_member(
            obj.get("substructure"),
            f"{ctx}.substructure",
            allowed_substructures,
        )
        raw_parameter = _require_str(obj.get("parameter"), f"{ctx}.parameter")
        parameter = normalize_parameter_name(raw_parameter)
        if parameter not in allowed_parameters:
            raise KBFactsValidationError(
                f"{ctx}.parameter '{raw_parameter}' normalized to '{parameter}' is not in allowed members: "
                f"{sorted(allowed_parameters)}"
            )
        metric = _require_member(obj.get("metric"), f"{ctx}.metric", allowed_metrics)
        direction = normalize_direction(
            _require_literal(obj.get("direction"), f"{ctx}.direction", VALID_DIRECTIONS)
        )
        confidence = _require_confidence(obj.get("confidence"), f"{ctx}.confidence")
        evidence_count = _require_non_negative_int(
            obj.get("evidence_count"), f"{ctx}.evidence_count"
        )
        evidence_iters = _require_iters(obj.get("evidence_iters"), f"{ctx}.evidence_iters")
        # topology_name = _require_topology(obj.get("topology"), f"{ctx}.topology", topology)
        topologies = _require_topology_or_topologies(obj, ctx, topology)

        normalized_facts.append(
            {
                "type": fact_type,
                "substructure": substructure,
                "parameter": parameter,
                "metric": metric,
                "direction": direction,
                "confidence": confidence,
                "evidence_count": evidence_count,
                "evidence_iters": evidence_iters,
                "topology": topology,
                "topologies": topologies,
            }
        )

    return {"facts": normalized_facts}


def validate_role_perf_payload(
    payload: Any,
    *,
    allowed_roles: Set[str],
    allowed_metrics: Set[str],
    topology: str,
) -> Dict[str, List[Dict[str, Any]]]:
    data = _require_payload(payload, context="kb_role_perf")
    facts = data["facts"]

    normalized_facts: List[Dict[str, Any]] = []
    for idx, fact in enumerate(facts):
        ctx = f"kb_role_perf.facts[{idx}]"
        obj = _require_dict(fact, ctx)
        _assert_keys(
            obj,
            [
                "type",
                "functional_role",
                "metric",
                "influence",
                "confidence",
                "evidence_count",
                "evidence_iters",
                "topology",
            ],
            ctx,
            allowed_extras=["topologies"],
        )

        fact_type = _require_literal(obj.get("type"), f"{ctx}.type", {"role_perf"})
        role = _require_member(obj.get("functional_role"), f"{ctx}.functional_role", allowed_roles)
        metric = _require_member(obj.get("metric"), f"{ctx}.metric", allowed_metrics)
        influence = _require_literal(obj.get("influence"), f"{ctx}.influence", VALID_INFLUENCE)
        confidence = _require_confidence(obj.get("confidence"), f"{ctx}.confidence")
        evidence_count = _require_non_negative_int(
            obj.get("evidence_count"), f"{ctx}.evidence_count"
        )
        evidence_iters = _require_iters(obj.get("evidence_iters"), f"{ctx}.evidence_iters")
        # topology_name = _require_topology(obj.get("topology"), f"{ctx}.topology", topology)
        topologies = _require_topology_or_topologies(obj, ctx, topology)

        normalized_facts.append(
            {
                "type": fact_type,
                "functional_role": role,
                "metric": metric,
                "influence": influence,
                "confidence": confidence,
                "evidence_count": evidence_count,
                "evidence_iters": evidence_iters,
                "topology": topology,
                "topologies": topologies,
            }
        )

    return {"facts": normalized_facts}


def _load_schema(filename: str) -> Dict[str, Any]:
    schema_path = Path(__file__).resolve().parent / filename
    if not schema_path.exists():
        raise FileNotFoundError(f"KB schema file not found: {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _require_payload(payload: Any, *, context: str) -> Dict[str, List[Any]]:
    data = _require_dict(payload, context)
    _assert_keys(data, ["facts"], context, allowed_extras=["topologies"])
    facts = data.get("facts")
    if not isinstance(facts, list):
        raise KBFactsValidationError(f"{context}.facts must be a JSON array.")
    return {"facts": facts}


def _require_dict(payload: Any, context: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise KBFactsValidationError(f"{context} must be a JSON object.")
    return payload


def _assert_keys(
    obj: Mapping[str, Any],
    required: Sequence[str],
    context: str,
    *,
    allowed_extras: Sequence[str] = (),
) -> None:
    required_set = set(required)
    allowed_extra_set = set(allowed_extras)
    keys = set(obj.keys())

    missing = sorted(required_set - keys)
    extras = sorted(keys - required_set - allowed_extra_set)

    if missing:
        raise KBFactsValidationError(f"{context} missing required keys: {missing}")
    if extras:
        raise KBFactsValidationError(f"{context} contains unknown keys: {extras}")


def _require_literal(value: Any, field: str, allowed: Set[str]) -> str:
    parsed = _require_str(value, field)
    if parsed not in allowed:
        raise KBFactsValidationError(f"{field} must be one of {sorted(allowed)}.")
    return parsed


def _require_member(value: Any, field: str, allowed: Set[str]) -> str:
    parsed = _require_str(value, field)
    if parsed not in allowed:
        raise KBFactsValidationError(f"{field} must be one of allowed values from input context.")
    return parsed


def _require_topology(value: Any, field: str, expected_topology: str) -> str:
    parsed = _require_str(value, field)
    if parsed != expected_topology:
        raise KBFactsValidationError(
            f"{field} must equal case topology '{expected_topology}', got '{parsed}'."
        )
    return parsed


def _require_topology_or_topologies(
    obj: Mapping[str, Any], ctx: str, expected_topology: str
) -> str:
    tops = obj.get("topologies")

    # if isinstance(topo, str) and topo.strip():
    # return _require_topology(topo, f"{ctx}.topology", expected_topology)
    # return expected_topology

    # if isinstance(tops, list) and tops:
    #     cleaned = [t for t in tops if isinstance(t, str) and t.strip()]
    # if expected_topology not in cleaned:
    #     raise KBFactsValidationError(
    #         f"{ctx}.topologies must include case topology '{expected_topology}', got {cleaned}."
    #     )
    # 校验通过后：标准化输出 topologies
    return tops

    # raise KBFactsValidationError(
    #     f"{ctx} must include 'topology' or non-empty 'topologies'."
    # )


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KBFactsValidationError(f"{field} must be a non-empty string.")
    return value


def _require_non_negative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise KBFactsValidationError(f"{field} must be a non-negative integer.")
    return value


def _require_confidence(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)):
        raise KBFactsValidationError(f"{field} must be a number in [0, 1].")
    parsed = float(value)
    if parsed < 0.0 or parsed > 1.0:
        raise KBFactsValidationError(f"{field} must be in [0, 1].")
    return parsed


def _require_iters(values: Any, field: str) -> List[int]:
    if not isinstance(values, list):
        raise KBFactsValidationError(f"{field} must be a list.")
    parsed: List[int] = []
    for idx, value in enumerate(values):
        if not isinstance(value, int) or value < 0:
            raise KBFactsValidationError(f"{field}[{idx}] must be a non-negative integer.")
        parsed.append(value)
    if len(parsed) > 8:
        raise KBFactsValidationError(f"{field} supports at most 8 iteration ids.")
    return parsed
