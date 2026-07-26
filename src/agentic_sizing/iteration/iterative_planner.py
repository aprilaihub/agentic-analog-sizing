from __future__ import annotations

import json
from typing import Any, Callable, Dict, Literal, Mapping, Optional

from ..kb.critical_heuristics import retrieve_critical_heuristics
from ..kb.interpreter import summarize_perf_tradeoff_facts, summarize_role_perf_facts
from ..llm.contract import LLMMessage, StructuredGenerationRequest, StructuredLLMClient
from ..llm.factory import create_structured_client
from ..resources import read_text
from .context import build_planner_context
from .schemas import (
    PLANNER_OUTPUT_SCHEMA,
    IterativeSchemaValidationError,
    validate_planner_payload,
)


class IterativePlannerError(RuntimeError):
    """Raised when iterative planner fails after retries."""


def run_iterative_planner(
    *,
    case_name: str,
    simulation_record_path: str,
    current_predicted_perfs: Mapping[str, float] | None,
    current_operation_region_summary: Mapping[str, Any] | None = None,
    enable_kb_input: bool = True,
    enable_heuristics: bool = True,
    anchor_status: Mapping[str, Any] | None = None,
    history: list[Any] | None = None,
    objective_when_feasible: bool = False,
    # current_perf_hint: str = "",
    provider: str = "openai",
    model: str = "gpt-5.2",
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = "high",
    max_retries: int = 2,
    temperature: float = 0.5,
    api_key: str | None = None,
    llm_client: StructuredLLMClient | None = None,
) -> Dict[str, Any]:
    context = build_planner_context(
        case_name=case_name,
        simulation_record_path=simulation_record_path,
        current_predicted_perfs=current_predicted_perfs,
        current_operation_region_summary=current_operation_region_summary,
        enable_kb_input=enable_kb_input,
        anchor_status=anchor_status,
        history=history,
        objective_when_feasible=objective_when_feasible,
    )

    unsatisfied_metrics = context["unsatisfied_metrics"]
    unsatisfied_names = [item["name"] for item in unsatisfied_metrics]
    if not unsatisfied_names:
        raise IterativePlannerError(
            "No unsatisfied metrics found; planner dispatch should not be invoked."
        )
    role_perf_summary = (
        summarize_role_perf_facts(
            context["role_perf_facts"],
            target_metrics=unsatisfied_names,
            allowed_roles=context["allowed_roles"],
        )
        if enable_kb_input
        else []
    )
    perf_tradeoff_summary = (
        summarize_perf_tradeoff_facts(
            context["perf_tradeoff_facts"],
            target_metrics=unsatisfied_names,
        )
        if enable_kb_input
        else []
    )
    critical_heuristics = (
        retrieve_critical_heuristics(
            case_name=case_name,
            target_metrics=unsatisfied_names,
            scope="planner",
        )
        if enable_kb_input and enable_heuristics
        else []
    )

    prompt = _render_prompt(
        _load_prompt("iterative_planner.md"),
        {
            "case_name": case_name,
            # "current_perf_hint": current_perf_hint,
            "unsatisfied_metrics_json": json.dumps(
                unsatisfied_metrics, indent=2, ensure_ascii=True
            ),
            "working_performances_json": json.dumps(
                context["working_performances"],
                indent=2,
                ensure_ascii=True,
            ),
            "planner_local_summary_json": json.dumps(
                context["planner_local_summary"],
                indent=2,
                ensure_ascii=True,
            ),
            "latest_record_json": json.dumps(context["latest_record"], indent=2, ensure_ascii=True),
            "recent_role_metric_selections_json": json.dumps(
                context["recent_role_metric_selections"],
                indent=2,
                ensure_ascii=True,
            ),
            "allowed_roles_json": json.dumps(context["allowed_roles"], indent=2, ensure_ascii=True),
            "settings_json": json.dumps(context["settings"], indent=2, ensure_ascii=True),
            "critical_heuristics_json": json.dumps(
                critical_heuristics, indent=2, ensure_ascii=True
            ),
            "critical_heuristics_block": (
                f"- Retrieved critical heuristics for this case and current metric set:\n{json.dumps(critical_heuristics, indent=2, ensure_ascii=True)}"
                if enable_kb_input and enable_heuristics
                else ""
            ),
            "role_perf_summary_json": json.dumps(role_perf_summary, indent=2, ensure_ascii=True),
            "role_perf_summary_block": (
                "Interpreted role-performance KB hints:\n"
                f"{json.dumps(role_perf_summary, indent=2, ensure_ascii=True)}"
                if enable_kb_input
                else ""
            ),
            "perf_tradeoff_summary_json": json.dumps(
                perf_tradeoff_summary,
                indent=2,
                ensure_ascii=True,
            ),
            "perf_tradeoff_summary_block": (
                "Interpreted performance-tradeoff KB hints:\n"
                f"{json.dumps(perf_tradeoff_summary, indent=2, ensure_ascii=True)}"
                if enable_kb_input
                else ""
            ),
        },
    )

    client = llm_client or create_structured_client(provider=provider, api_key=api_key)

    validated = _run_with_retries(
        stage_name=f"iterative_planner[{case_name}]",
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
                                "You are an analog IC iterative sizing planner. Return strict JSON only and "
                                "follow schema exactly."
                            ),
                        ),
                        LLMMessage(role="user", content=prompt),
                    ],
                    schema_name="iterative_planner_output",
                    schema=PLANNER_OUTPUT_SCHEMA,
                    strict=True,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            )
        ),
        validator=lambda payload: validate_planner_payload(
            payload,
            unsatisfied_metrics=set(unsatisfied_names),
            allowed_roles=set(context["allowed_roles"]),
        ),
    )

    validated["unsatisfied_metrics"] = unsatisfied_names
    validated["unsatisfied_metric_details"] = unsatisfied_metrics
    return validated


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

    raise IterativePlannerError(
        f"{stage_name} failed after {max_retries + 1} attempts: {last_error}"
    ) from last_error


def _extract_payload(result: Any) -> Dict[str, Any]:
    payload = result.output_json
    if not isinstance(payload, dict):
        raise IterativeSchemaValidationError("iterative planner output must be a JSON object")
    return payload


def _load_prompt(filename: str) -> str:
    return read_text("prompts", "iteration", filename)


def _render_prompt(template: str, replacements: Dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered
