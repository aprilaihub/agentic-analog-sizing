from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Set

from ..llm.contract import (
    LLMMessage,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    StructuredLLMClient,
)
from ..llm.factory import create_structured_client
from ..resources import read_text
from .critical_heuristics import (
    CRITICAL_HEURISTICS_SCHEMA,
    validate_critical_heuristics_payload,
    write_case_and_rebuild_global_heuristics,
)
from .schemas import (
    KBFactsValidationError,
    load_kb_perf_tradeoff_schema,
    load_kb_role_perf_schema,
    load_kb_substruct_param_perf_schema,
    normalize_parameter_name,
    validate_perf_tradeoff_payload,
    validate_role_perf_payload,
    validate_substruct_param_perf_payload,
)


class KBFactExtractionError(RuntimeError):
    """Raised when KB fact extraction fails after retries."""


MIN_FACT_COUNTS: Dict[str, int] = {
    "perf_tradeoff": 3,
    "substruct_param_perf": 8,
    "role_perf": 4,
}


def run_kb_fact_extraction(
    settings_path: str,
    improving_designs_path: str,
    tagging_path: str,
    output_dir: str | None = None,
    output_prefix: str | None = None,
    provider: str = "openai",
    model: str = "gpt-5.2",
    max_retries: int = 2,
    temperature: float = 0.5,
    reasoning_effort: Literal["low", "medium", "high"] = "low",
    api_key: str | None = None,
    llm_client: StructuredLLMClient | None = None,
    generate_heuristics: bool = True,
    heuristics_output_dir: str | None = None,
) -> Dict[str, Any]:
    settings_file = _resolve_existing_file(settings_path, "settings")
    improving_designs_file = _resolve_existing_file(improving_designs_path, "improving designs")
    tagging_file = _resolve_existing_file(tagging_path, "tagging")

    settings_json = _load_json_file(settings_file, "settings")
    improving_designs_json = _load_json_file(improving_designs_file, "improving designs")
    tagging_json = _load_json_file(tagging_file, "tagging")

    case_name = _infer_case_name(settings_file)
    metrics = _extract_allowed_metrics(settings_json)
    parameters = _extract_allowed_parameters(settings_json)
    role_names = _extract_allowed_role_names(tagging_json)
    substructure_names = _extract_allowed_substructures(tagging_json)

    shared_replacements = {
        "user_settings_json": json.dumps(settings_json, indent=2, ensure_ascii=True),
        "best_trace_json": json.dumps(improving_designs_json, indent=2, ensure_ascii=True),
        "structural_tagging_json": json.dumps(tagging_json, indent=2, ensure_ascii=True),
        "topology_name": case_name,
    }

    client = llm_client or create_structured_client(provider=provider, api_key=api_key)

    step1_prompt = _render_prompt(
        _load_prompt("step1_perf_tradeoff.md"),
        shared_replacements,
    )
    step1_payload = _run_with_retries(
        stage_name="kb_step1_perf_tradeoff",
        max_retries=max_retries,
        producer=lambda: _extract_payload(
            client.generate_structured(
                StructuredGenerationRequest(
                    provider=provider,
                    model=model,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "You are an analog design knowledge extraction engine. "
                                "Return strict JSON only."
                            ),
                        ),
                        LLMMessage(role="user", content=step1_prompt),
                    ],
                    schema_name="kb_perf_tradeoff",
                    schema=load_kb_perf_tradeoff_schema(),
                    strict=True,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            )
        ),
        validator=lambda payload: _enforce_min_count(
            validate_perf_tradeoff_payload(
                payload,
                allowed_metrics=metrics,
                topology=case_name,
            ),
            stage_key="perf_tradeoff",
        ),
    )

    step2_prompt = _render_prompt(
        _load_prompt("step2_substruct_param_perf.md"),
        {
            **shared_replacements,
            "step1_perf_tradeoff_json": json.dumps(step1_payload, indent=2, ensure_ascii=True),
        },
    )
    step2_payload = _run_with_retries(
        stage_name="kb_step2_substruct_param_perf",
        max_retries=max_retries,
        producer=lambda: _extract_payload(
            client.generate_structured(
                StructuredGenerationRequest(
                    provider=provider,
                    model=model,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "You are an analog design knowledge extraction engine. "
                                "Return strict JSON only and avoid low-evidence relations."
                            ),
                        ),
                        LLMMessage(role="user", content=step2_prompt),
                    ],
                    schema_name="kb_substruct_param_perf",
                    schema=load_kb_substruct_param_perf_schema(),
                    strict=True,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            )
        ),
        validator=lambda payload: _enforce_min_count(
            validate_substruct_param_perf_payload(
                payload,
                allowed_substructures=substructure_names,
                allowed_parameters=parameters,
                allowed_metrics=metrics,
                topology=case_name,
            ),
            stage_key="substruct_param_perf",
        ),
    )

    step3_prompt = _render_prompt(
        _load_prompt("step3_role_perf.md"),
        {
            **shared_replacements,
            "step1_perf_tradeoff_json": json.dumps(step1_payload, indent=2, ensure_ascii=True),
            "step2_substruct_param_perf_json": json.dumps(
                step2_payload, indent=2, ensure_ascii=True
            ),
        },
    )
    step3_payload = _run_with_retries(
        stage_name="kb_step3_role_perf",
        max_retries=max_retries,
        producer=lambda: _extract_payload(
            client.generate_structured(
                StructuredGenerationRequest(
                    provider=provider,
                    model=model,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "You are an analog design knowledge extraction engine. "
                                "Return strict JSON only with role-level insights."
                            ),
                        ),
                        LLMMessage(role="user", content=step3_prompt),
                    ],
                    schema_name="kb_role_perf",
                    schema=load_kb_role_perf_schema(),
                    strict=True,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            )
        ),
        validator=lambda payload: _enforce_min_count(
            _ensure_role_metric_coverage(
                validate_role_perf_payload(
                    payload,
                    allowed_roles=role_names,
                    allowed_metrics=metrics,
                    topology=case_name,
                ),
                allowed_roles=role_names,
                topology=case_name,
            ),
            stage_key="role_perf",
        ),
    )

    heuristic_items: list[Dict[str, Any]] = []
    heuristic_files: dict[str, str] = {}
    if generate_heuristics:
        step4_prompt = _render_prompt(
            _load_prompt("step4_transferable_heuristics.md"),
            {
                **shared_replacements,
                "step1_perf_tradeoff_json": json.dumps(step1_payload, indent=2, ensure_ascii=True),
                "step2_substruct_param_perf_json": json.dumps(
                    step2_payload, indent=2, ensure_ascii=True
                ),
                "step3_role_perf_json": json.dumps(step3_payload, indent=2, ensure_ascii=True),
            },
        )
        step4_payload = _run_with_retries(
            stage_name="kb_step4_transferable_heuristics",
            max_retries=max_retries,
            producer=lambda: _extract_payload(
                client.generate_structured(
                    StructuredGenerationRequest(
                        provider=provider,
                        model=model,
                        messages=[
                            LLMMessage(
                                role="system",
                                content=(
                                    "You extract transferable analog design strategies. "
                                    "Return strict JSON only and avoid topology-specific recipes."
                                ),
                            ),
                            LLMMessage(role="user", content=step4_prompt),
                        ],
                        schema_name="critical_heuristics",
                        schema=CRITICAL_HEURISTICS_SCHEMA,
                        strict=True,
                        temperature=temperature,
                        reasoning_effort=reasoning_effort,
                    )
                )
            ),
            validator=lambda payload: {
                "heuristics": validate_critical_heuristics_payload(
                    payload,
                    case_name=case_name,
                    allowed_metrics=metrics,
                )
            },
        )
        heuristic_items = step4_payload["heuristics"]
        heuristic_files = write_case_and_rebuild_global_heuristics(
            case_name=case_name,
            heuristics=heuristic_items,
            base_dir=heuristics_output_dir,
        )

    target_paths = _resolve_output_files(
        settings_file=settings_file,
        output_dir=output_dir,
        output_prefix=output_prefix,
    )
    for key, payload in (
        ("perf_tradeoff", step1_payload),
        ("substruct_param_perf", step2_payload),
        ("role_perf", step3_payload),
    ):
        target = target_paths[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        payload_to_write = _drop_verbose_fact_fields(payload)
        target.write_text(
            json.dumps(payload_to_write, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    return {
        "perf_tradeoff": step1_payload,
        "substruct_param_perf": step2_payload,
        "role_perf": step3_payload,
        "critical_heuristics": heuristic_items,
        "critical_heuristic_files": heuristic_files,
        "output_files": {key: str(path) for key, path in target_paths.items()},
    }


def _run_with_retries(
    stage_name: str,
    max_retries: int,
    producer: Callable[[], Dict[str, Any]],
    validator: Callable[[Any], Dict[str, Any]],
) -> Dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            produced = producer()
            return validator(produced)
        except Exception as exc:  # pragma: no cover - exercised via retry behavior tests
            last_error = exc
            if attempt >= max_retries:
                break

    raise KBFactExtractionError(
        f"{stage_name} failed after {max_retries + 1} attempts: {last_error}"
    ) from last_error


def _enforce_min_count(payload: Dict[str, Any], stage_key: str) -> Dict[str, Any]:
    required = MIN_FACT_COUNTS[stage_key]
    actual = len(payload.get("facts", []))
    if actual < required:
        raise KBFactsValidationError(
            f"{stage_key} fact count {actual} is below required minimum {required}."
        )
    return payload


def _ensure_role_metric_coverage(
    payload: Dict[str, Any],
    *,
    allowed_roles: Set[str],
    topology: str,
) -> Dict[str, Any]:
    facts = payload.get("facts")
    if not isinstance(facts, list) or not allowed_roles:
        return payload

    influence_rank = {"dominant": 0, "significant": 1, "weak": 2}
    next_weaker = {"dominant": "significant", "significant": "weak", "weak": "weak"}
    synthesized_caps = {"dominant": 0.55, "significant": 0.45, "weak": 0.35}

    metric_to_facts: dict[str, list[Dict[str, Any]]] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if fact.get("type") != "role_perf":
            continue
        metric = fact.get("metric")
        role = fact.get("functional_role")
        if isinstance(metric, str) and metric and isinstance(role, str) and role:
            metric_to_facts.setdefault(metric, []).append(fact)

    if not metric_to_facts:
        return payload

    augmented = list(facts)
    for metric, metric_facts in metric_to_facts.items():
        present_roles = {
            fact["functional_role"]
            for fact in metric_facts
            if isinstance(fact.get("functional_role"), str)
        }
        missing_roles = sorted(allowed_roles - present_roles)
        if not missing_roles:
            continue

        weakest_fact = max(
            metric_facts,
            key=lambda fact: influence_rank.get(str(fact.get("influence")), influence_rank["weak"]),
        )
        weakest_influence = str(weakest_fact.get("influence", "weak"))
        fallback_influence = next_weaker.get(weakest_influence, "weak")
        base_confidence = min(
            float(fact.get("confidence", 0.0))
            for fact in metric_facts
            if isinstance(fact.get("confidence"), (int, float))
        )
        fallback_confidence = round(
            min(base_confidence * 0.8, synthesized_caps[fallback_influence]),
            6,
        )
        topology_union = sorted(
            {
                topo
                for fact in metric_facts
                for topo in (
                    fact.get("topologies")
                    if isinstance(fact.get("topologies"), list)
                    else [fact.get("topology")]
                )
                if isinstance(topo, str) and topo
            }
        ) or [topology]

        for role in missing_roles:
            augmented.append(
                {
                    "type": "role_perf",
                    "functional_role": role,
                    "metric": metric,
                    "influence": fallback_influence,
                    "confidence": fallback_confidence,
                    "evidence_count": 0,
                    "evidence_iters": [],
                    "topology": topology,
                    "topologies": topology_union,
                }
            )

    return {"facts": augmented}


def _extract_payload(result: StructuredGenerationResult) -> Dict[str, Any]:
    payload = result.output_json
    if not isinstance(payload, dict):
        raise RuntimeError("Structured response must be a JSON object.")
    return payload


def _drop_verbose_fact_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    facts = payload.get("facts")
    if not isinstance(facts, list):
        return payload

    cleaned_facts: list[Dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            cleaned_facts.append(fact)
            continue

        cleaned_fact = dict(fact)
        cleaned_fact.pop("topologies", None)
        cleaned_fact.pop("evidence_iters", None)
        cleaned_facts.append(cleaned_fact)

    cleaned_payload = dict(payload)
    cleaned_payload["facts"] = cleaned_facts
    return cleaned_payload


def _resolve_existing_file(path: str, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"{label} file not found: {resolved}")
    return resolved


def _load_json_file(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} file is not valid JSON: {path}") from exc


def _load_prompt(filename: str) -> str:
    return read_text("prompts", "kb", filename)


def _render_prompt(template: str, replacements: Dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def _extract_allowed_metrics(settings_json: Any) -> Set[str]:
    responses = settings_json.get("responses") if isinstance(settings_json, dict) else None
    assembler = responses.get("assembler") if isinstance(responses, dict) else None
    if not isinstance(assembler, list):
        raise ValueError("settings.responses.assembler must be a JSON array.")

    metrics = {item for item in assembler if isinstance(item, str) and item.strip()}
    if not metrics:
        raise ValueError("settings.responses.assembler must contain at least one metric string.")
    return metrics


def _extract_allowed_parameters(settings_json: Any) -> Set[str]:
    des_vars = settings_json.get("des_vars") if isinstance(settings_json, dict) else None
    if not isinstance(des_vars, dict):
        raise ValueError("settings.des_vars must be a JSON object.")

    parameters = {
        normalize_parameter_name(key)
        for key in des_vars.keys()
        if isinstance(key, str) and key.strip()
    }
    if not parameters:
        raise ValueError("settings.des_vars must contain at least one design variable key.")
    return parameters


def _extract_allowed_role_names(tagging_json: Any) -> Set[str]:
    if not isinstance(tagging_json, dict):
        raise ValueError("tagging JSON must be a JSON object.")

    stage1 = tagging_json.get("stage1")
    if not isinstance(stage1, dict):
        raise ValueError("tagging.stage1 must be a JSON object.")

    functional_roles = stage1.get("functional_roles")
    if not isinstance(functional_roles, list):
        raise ValueError("tagging.stage1.functional_roles must be a JSON array.")

    roles: Set[str] = set()
    for idx, role in enumerate(functional_roles):
        if not isinstance(role, dict):
            raise ValueError(f"tagging.stage1.functional_roles[{idx}] must be a JSON object.")
        name = role.get("name")
        if isinstance(name, str) and name.strip():
            roles.add(name)

    if not roles:
        raise ValueError("tagging.stage1.functional_roles must contain at least one role name.")
    return roles


def _extract_allowed_substructures(tagging_json: Any) -> Set[str]:
    if not isinstance(tagging_json, dict):
        raise ValueError("tagging JSON must be a JSON object.")

    stage2 = tagging_json.get("stage2")
    if not isinstance(stage2, dict):
        raise ValueError("tagging.stage2 must be a JSON object.")

    roles = stage2.get("roles")
    if not isinstance(roles, list):
        raise ValueError("tagging.stage2.roles must be a JSON array.")

    substructures: Set[str] = set()
    for role_idx, role in enumerate(roles):
        if not isinstance(role, dict):
            raise ValueError(f"tagging.stage2.roles[{role_idx}] must be a JSON object.")
        entries = role.get("substructures")
        if not isinstance(entries, list):
            raise ValueError(
                f"tagging.stage2.roles[{role_idx}].substructures must be a JSON array."
            )

        for sub_idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"tagging.stage2.roles[{role_idx}].substructures[{sub_idx}] must be a JSON object."
                )
            type_name = entry.get("type")
            if isinstance(type_name, str) and type_name.strip():
                substructures.add(type_name)

    if not substructures:
        raise ValueError("tagging.stage2.roles[*].substructures must contain at least one type.")
    return substructures


def _infer_case_name(settings_file: Path) -> str:
    stem = settings_file.stem
    if stem.endswith("_settings"):
        case_name = stem[: -len("_settings")]
    else:
        case_name = stem

    case_name = case_name.strip()
    if not case_name:
        raise ValueError(f"Cannot infer case name from settings file: {settings_file}")
    return case_name


def _resolve_output_files(
    *,
    settings_file: Path,
    output_dir: str | None,
    output_prefix: str | None,
) -> Dict[str, Path]:
    base_dir = Path(output_dir).expanduser().resolve() if output_dir else settings_file.parent
    prefix = (
        output_prefix.strip() if isinstance(output_prefix, str) else _infer_case_name(settings_file)
    )
    if not prefix:
        raise ValueError("output_prefix cannot be empty.")

    return {
        "perf_tradeoff": base_dir / f"{prefix}_kb_perf_tradeoff.json",
        "substruct_param_perf": base_dir / f"{prefix}_kb_substruct_param_perf.json",
        "role_perf": base_dir / f"{prefix}_kb_role_perf.json",
    }
