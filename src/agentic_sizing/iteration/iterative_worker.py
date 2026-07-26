from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence

from ..kb.critical_heuristics import retrieve_critical_heuristics
from ..kb.interpreter import summarize_substruct_param_perf_facts
from ..llm.contract import LLMMessage, StructuredGenerationRequest, StructuredLLMClient
from ..llm.factory import create_structured_client
from ..resources import read_text
from .context import build_worker_context
from .schemas import (
    IterativeSchemaValidationError,
    build_worker_output_schema,
    validate_worker_payload,
)


class IterativeWorkerError(RuntimeError):
    """Raised when iterative worker fails after retries."""


def run_iterative_worker(
    *,
    case_name: str,
    role_name: str,
    target_metric: str,
    worker_instruction: str,
    simulation_record_path: str,
    current_design_vars: Mapping[str, float] | None,
    current_predicted_perfs: Mapping[str, float] | None,
    current_operation_region_summary: Mapping[str, Any] | None = None,
    enable_kb_input: bool = True,
    enable_heuristics: bool = True,
    anchor_status: Mapping[str, Any] | None = None,
    provider: str = "openai",
    model: str = "gpt-5.2",
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = "high",
    max_retries: int = 2,
    temperature: float = 0.5,
    api_key: str | None = None,
    llm_client: StructuredLLMClient | None = None,
) -> Dict[str, Any]:
    if not role_name.strip():
        raise ValueError("role_name must be non-empty")
    if not target_metric.strip():
        raise ValueError("target_metric must be non-empty")
    if not worker_instruction.strip():
        raise ValueError("worker_instruction must be non-empty")

    context = build_worker_context(
        case_name=case_name,
        role_name=role_name,
        target_metric=target_metric,
        simulation_record_path=simulation_record_path,
        current_design_vars=current_design_vars,
        current_predicted_perfs=current_predicted_perfs,
        current_operation_region_summary=current_operation_region_summary,
        enable_kb_input=enable_kb_input,
        anchor_status=anchor_status,
    )
    candidate_count = 1
    kb_enabled = bool(enable_kb_input)
    kb_substruct_param_perf_summary = (
        summarize_substruct_param_perf_facts(
            context["kb_substruct_param_perf"],
            target_metrics=[target_metric],
        )
        if kb_enabled
        else []
    )
    critical_heuristics = (
        retrieve_critical_heuristics(
            case_name=case_name,
            target_metric=target_metric,
            scope="worker",
        )
        if kb_enabled and enable_heuristics
        else []
    )

    prompt = _render_prompt(
        _load_prompt("iterative_worker.md"),
        {
            "case_name": case_name,
            "role_name": role_name,
            "target_metric": target_metric,
            "worker_instruction": worker_instruction,
            "candidate_count_phrase": _candidate_count_phrase(candidate_count),
            "candidate_variation_rule": _candidate_variation_rule(candidate_count),
            "candidate_examples_block": _candidate_examples_block(candidate_count),
            "prediction_task_block": _prediction_task_block(),
            "prediction_rules_block": _prediction_rules_block(),
            "role_substructures_json": json.dumps(
                context["role_substructures"],
                indent=2,
                ensure_ascii=True,
            ),
            "variable_bounds_json": json.dumps(
                context["variable_bounds"], indent=2, ensure_ascii=True
            ),
            "worker_local_summary_json": json.dumps(
                context["worker_local_summary"],
                indent=2,
                ensure_ascii=True,
            ),
            "working_state_json": json.dumps(context["working_state"], indent=2, ensure_ascii=True),
            "design_specs_json": json.dumps(context["design_specs"], indent=2, ensure_ascii=True),
            "critical_heuristics_json": json.dumps(
                critical_heuristics, indent=2, ensure_ascii=True
            ),
            "critical_heuristics_block": (
                f"- Retrieved critical heuristics for this case and target:\n{json.dumps(critical_heuristics, indent=2, ensure_ascii=True)}"
                if kb_enabled and enable_heuristics
                else ""
            ),
            "latest_results_json": json.dumps(
                context["latest_results"],
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            "improving_best_json": json.dumps(
                context["improving_design_samples"]["best"],
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            "kb_substruct_param_perf_summary_json": json.dumps(
                kb_substruct_param_perf_summary,
                indent=2,
                ensure_ascii=True,
            ),
            "kb_substruct_param_perf_summary_block": (
                "Interpreted substructure-parameter-performance KB hints:\n"
                f"{json.dumps(kb_substruct_param_perf_summary, indent=2, ensure_ascii=True)}"
                if kb_enabled
                else ""
            ),
        },
    )
    _maybe_sample_worker_prompt(
        simulation_record_path=simulation_record_path,
        case_name=case_name,
        role_name=role_name,
        target_metric=target_metric,
        worker_instruction=worker_instruction,
        prompt=prompt,
    )

    client = llm_client or create_structured_client(provider=provider, api_key=api_key)
    validated_payload = _run_with_retries(
        stage_name=f"iterative_worker[{case_name}:{role_name}:{target_metric}]",
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
                                "You are an analog IC role worker. Return strict JSON only, keep updates within "
                                f"role variable bounds, and emit exactly {candidate_count} "
                                f"{'candidate' if candidate_count == 1 else 'distinct candidates'}. "
                                "Predict the complete absolute performance vector."
                            ),
                        ),
                        LLMMessage(role="user", content=prompt),
                    ],
                    schema_name="iterative_worker_output",
                    schema=build_worker_output_schema(candidate_count),
                    strict=True,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            )
        ),
        validator=lambda payload: validate_worker_payload(
            payload,
            expected_role_name=role_name,
            expected_target_metric=target_metric,
            allowed_variables=set(context["role_variables"]),
            variable_bounds=context["variable_bounds"],
            required_performance_metrics=set(context["required_performance_metrics"]),
            expected_candidate_count=candidate_count,
            require_predicted_performances=True,
        ),
    )

    validated_candidates = _dedupe_candidates(validated_payload["candidates"])
    selected = dict(validated_candidates[0])
    selected["role_name"] = role_name
    selected["target_metric"] = target_metric
    selected["candidate_count_sampled"] = len(validated_candidates)
    selected["overall_rationale"] = validated_payload["rationale"]
    return selected


def _run_with_retries(
    *,
    stage_name: str,
    max_retries: int,
    producer: Callable[[], Dict[str, Any]],
    validator: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return validator(producer())
        except Exception as exc:  # pragma: no cover - retry behavior tested separately
            last_error = exc
            if attempt >= max_retries:
                break

    raise IterativeWorkerError(
        f"{stage_name} failed after {max_retries + 1} attempts: {last_error}"
    ) from last_error


def _extract_payload(result: Any) -> Dict[str, Any]:
    payload = result.output_json
    if not isinstance(payload, dict):
        raise IterativeSchemaValidationError("iterative worker output must be a JSON object")
    return payload


def _load_prompt(filename: str) -> str:
    return read_text("prompts", "iteration", filename)


def _render_prompt(template: str, replacements: Dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def _maybe_sample_worker_prompt(
    *,
    simulation_record_path: str,
    case_name: str,
    role_name: str,
    target_metric: str,
    worker_instruction: str,
    prompt: str,
) -> None:
    record_path = Path(simulation_record_path).expanduser().resolve()
    state_path = record_path.parent / f"{record_path.stem}_worker_prompt_sample.state.json"
    log_path = record_path.parent / f"{record_path.stem}_worker_prompt_sample.txt"

    try:
        sample_state = _load_prompt_sample_state(state_path)
        seen_worker_calls = int(sample_state.get("seen_worker_calls", 0)) + 1
        timestamp = datetime.now(timezone.utc).isoformat()

        _write_json_file(
            state_path,
            {
                "seen_worker_calls": seen_worker_calls,
                "last_updated_at_utc": timestamp,
                "sample_log_path": str(log_path),
                "sampling_method": "latest_only_overwrite",
                "logged_prompt_count": 1,
            },
        )

        _write_text_file(
            log_path,
            _format_prompt_log_text(
                sampled_at_utc=timestamp,
                seen_worker_calls=seen_worker_calls,
                case_name=case_name,
                role_name=role_name,
                target_metric=target_metric,
                worker_instruction=worker_instruction,
                simulation_record_path=str(record_path),
                prompt=prompt,
            ),
        )
    except OSError:
        return


def _load_prompt_sample_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _format_prompt_log_text(
    *,
    sampled_at_utc: str,
    seen_worker_calls: int,
    case_name: str,
    role_name: str,
    target_metric: str,
    worker_instruction: str,
    simulation_record_path: str,
    prompt: str,
) -> str:
    header_lines = [
        f"sampled_at_utc: {sampled_at_utc}",
        "sampling_method: latest_only_overwrite",
        f"seen_worker_calls: {seen_worker_calls}",
        f"case_name: {case_name}",
        f"role_name: {role_name}",
        f"target_metric: {target_metric}",
        f"simulation_record_path: {simulation_record_path}",
        "worker_instruction:",
        worker_instruction,
        "",
        "prompt:",
        prompt.rstrip(),
        "",
    ]
    return "\n".join(header_lines)


def _prediction_task_block() -> str:
    return "- Predict absolute values for all performance metrics for the candidate."


def _prediction_rules_block() -> str:
    return (
        "- The candidate's `predicted_performances` must cover all metrics in design specs exactly once.\n"
        "- Predicted values must be absolute values, not deltas.\n"
        "- Ensure predicted performance changes are consistent with either the substructure "
        "parameter-perf relationships or the latest records."
    )


def _prediction_output_block() -> str:
    return (
        '      "predicted_performances": [\n'
        '        {"name": "...", "value": 0.0, "reason": "..."}\n'
        "      ],\n"
    )


def _candidate_count_phrase(candidate_count: int) -> str:
    if candidate_count == 1:
        return "exactly 1 candidate update"
    return f"exactly {candidate_count} distinct candidate updates"


def _candidate_variation_rule(candidate_count: int) -> str:
    if candidate_count == 1:
        return ""
    return (
        f"- Make the {candidate_count} candidates meaningfully different in step size, direction, "
        "or tradeoff emphasis; do not return near-duplicates."
    )


def _candidate_examples_block(candidate_count: int) -> str:
    blocks: List[str] = []
    for idx in range(candidate_count):
        suffix = "," if idx < candidate_count - 1 else ""
        blocks.append(
            "    {\n"
            '      "updated_design_vars": [\n'
            '        {"name": "...", "value": 0.0, "reason": "..."}\n'
            "      ],\n"
            f"{_prediction_output_block()}"
            '      "rationale": "..."\n'
            f"    }}{suffix}"
        )
    return "\n".join(blocks)


def _dedupe_candidates(candidates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for candidate in candidates:
        key = tuple(
            sorted(
                (str(item["name"]), float(item["value"]))
                for item in candidate.get("updated_design_vars", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("name"), str)
                and isinstance(item.get("value"), (int, float))
            )
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(candidate))
    return deduped or [dict(candidate) for candidate in candidates]
