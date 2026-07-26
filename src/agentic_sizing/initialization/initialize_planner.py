from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional, Set

from ..core.llm_metric_ranges import annotate_design_specs_for_llm, annotate_settings_for_llm
from ..core.operation_region import is_operation_region_metric
from ..kb.critical_heuristics import retrieve_critical_heuristics
from ..kb.interpreter import summarize_perf_tradeoff_facts, summarize_role_perf_facts
from ..llm.contract import LLMMessage, StructuredGenerationRequest, StructuredLLMClient
from ..llm.factory import create_structured_client
from ..resources import read_text
from .schemas import (
    PLANNER_OUTPUT_SCHEMA,
    InitializeSchemaValidationError,
    validate_planner_payload,
)


class InitializePlannerError(RuntimeError):
    """Raised when initialize planner fails after retries."""


SYNTHETIC_CONTROL_ROLE = "Testbench and bias controls"


def run_initialize_planner(
    settings_path: str,
    tagging_path: str,
    kb_perf_tradeoff_path: str,
    kb_role_perf_path: str,
    design_specs_path: str,
    enable_kb_input: bool = True,
    enable_heuristics: bool = True,
    provider: str = "openai",
    model: str = "gpt-5.2",
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = "high",
    max_retries: int = 2,
    temperature: float = 0.5,
    api_key: str | None = None,
    llm_client: StructuredLLMClient | None = None,
) -> Dict[str, Any]:
    settings_file = _resolve_existing_file(settings_path, "settings")
    tagging_file = _resolve_existing_file(tagging_path, "tagging")
    kb_perf_tradeoff_file = (
        _resolve_existing_file(kb_perf_tradeoff_path, "kb perf tradeoff")
        if enable_kb_input
        else None
    )
    kb_role_perf_file = (
        _resolve_existing_file(kb_role_perf_path, "kb role perf") if enable_kb_input else None
    )
    design_specs_file = _resolve_existing_file(design_specs_path, "design specs")

    settings_json = _load_json_file(settings_file, "settings")
    tagging_json = _load_json_file(tagging_file, "tagging")
    kb_perf_tradeoff_json = (
        _load_json_file(kb_perf_tradeoff_file, "kb perf tradeoff")
        if kb_perf_tradeoff_file is not None
        else {"facts": []}
    )
    kb_role_perf_json = (
        _load_json_file(kb_role_perf_file, "kb role perf")
        if kb_role_perf_file is not None
        else {"facts": []}
    )
    design_specs_json = _load_json_file(design_specs_file, "design specs")
    prompt_design_specs_json = _hide_objective_metric_for_initialization(design_specs_json)
    prompt_settings_json = _hide_objective_metric_from_settings(settings_json, design_specs_json)
    prompt_design_specs_json = annotate_design_specs_for_llm(prompt_design_specs_json)
    prompt_settings_json = annotate_settings_for_llm(prompt_settings_json)

    allowed_roles = _extract_allowed_roles(tagging_json, settings_json)
    allowed_metrics = _extract_allowed_metrics(prompt_design_specs_json)
    case_name = _infer_case_name_from_settings_path(settings_file)
    kb_perf_tradeoff_summary = (
        summarize_perf_tradeoff_facts(
            kb_perf_tradeoff_json,
            target_metrics=allowed_metrics,
        )
        if enable_kb_input and enable_heuristics
        else []
    )
    kb_role_perf_summary = (
        summarize_role_perf_facts(
            kb_role_perf_json,
            target_metrics=allowed_metrics,
            allowed_roles=allowed_roles,
        )
        if enable_kb_input
        else []
    )
    critical_heuristics = (
        retrieve_critical_heuristics(
            case_name=case_name,
            target_metrics=sorted(allowed_metrics),
            scope="planner",
        )
        if enable_kb_input and enable_heuristics
        else []
    )
    prompt = _render_prompt(
        _load_prompt("initialize_planner.md"),
        {
            "settings_json": json.dumps(prompt_settings_json, indent=2, ensure_ascii=True),
            "tagging_json": json.dumps(
                _trim_tagging_for_prompt(tagging_json), indent=2, ensure_ascii=True
            ),
            "kb_perf_tradeoff_summary_json": json.dumps(
                kb_perf_tradeoff_summary, indent=2, ensure_ascii=True
            ),
            "kb_role_perf_summary_json": json.dumps(
                kb_role_perf_summary, indent=2, ensure_ascii=True
            ),
            "critical_heuristics_json": json.dumps(
                critical_heuristics, indent=2, ensure_ascii=True
            ),
            "critical_heuristics_block": (
                f"- Retrieved critical heuristics for this case:\n{json.dumps(critical_heuristics, indent=2, ensure_ascii=True)}"
                if enable_kb_input and enable_heuristics
                else ""
            ),
            "kb_perf_tradeoff_summary_block": (
                "Interpreted KB perf-tradeoff hints:\n"
                f"{json.dumps(kb_perf_tradeoff_summary, indent=2, ensure_ascii=True)}"
                if enable_kb_input
                else ""
            ),
            "kb_role_perf_summary_block": (
                "Interpreted KB role-performance hints:\n"
                f"{json.dumps(kb_role_perf_summary, indent=2, ensure_ascii=True)}"
                if enable_kb_input
                else ""
            ),
            "design_specs_json": json.dumps(prompt_design_specs_json, indent=2, ensure_ascii=True),
            "allowed_roles_json": json.dumps(sorted(allowed_roles), indent=2, ensure_ascii=True),
            "allowed_metrics_json": json.dumps(
                sorted(allowed_metrics), indent=2, ensure_ascii=True
            ),
        },
    )

    client = llm_client or create_structured_client(provider=provider, api_key=api_key)

    return _run_with_retries(
        stage_name="initialize_planner",
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
                                "You are an analog IC initialize planner. Return strict JSON only and strictly "
                                "follow the schema."
                            ),
                        ),
                        LLMMessage(role="user", content=prompt),
                    ],
                    schema_name="initialize_planner_output",
                    schema=PLANNER_OUTPUT_SCHEMA,
                    strict=True,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            )
        ),
        validator=lambda payload: validate_planner_payload(
            payload,
            allowed_roles=allowed_roles,
            allowed_metrics=allowed_metrics,
        ),
    )


def _run_with_retries(
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

    raise InitializePlannerError(
        f"{stage_name} failed after {max_retries + 1} attempts: {last_error}"
    ) from last_error


def _extract_payload(result: Any) -> Dict[str, Any]:
    payload = result.output_json
    if not isinstance(payload, dict):
        raise InitializeSchemaValidationError("initialize planner output must be a JSON object.")
    return payload


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


def _infer_case_name_from_settings_path(settings_path: Path) -> str:
    stem = settings_path.stem
    if stem.endswith("_settings"):
        return stem[: -len("_settings")]
    return stem


def _extract_allowed_roles(tagging_json: Any, settings_json: Any) -> Set[str]:
    if not isinstance(tagging_json, dict):
        raise ValueError("tagging must be a JSON object")
    stage1 = tagging_json.get("stage1")
    if not isinstance(stage1, dict):
        raise ValueError("tagging.stage1 must be a JSON object")
    roles = stage1.get("functional_roles")
    if not isinstance(roles, list):
        raise ValueError("tagging.stage1.functional_roles must be a JSON array")

    names = {
        role.get("name")
        for role in roles
        if isinstance(role, dict)
        and isinstance(role.get("name"), str)
        and role.get("name", "").strip()
    }
    names = {name for name in names if isinstance(name, str)}

    stage2_editable_roles = _extract_stage2_roles_with_design_variables(tagging_json)
    if stage2_editable_roles:
        names &= stage2_editable_roles
    elif _has_design_variables(settings_json):
        names = set()

    if _extract_unowned_design_variables(
        tagging_json, settings_json if isinstance(settings_json, dict) else {}
    ):
        names.add(SYNTHETIC_CONTROL_ROLE)
    if not names:
        raise ValueError("tagging.stage1.functional_roles must contain at least one role name")
    return names


def _has_design_variables(settings_json: Any) -> bool:
    des_vars = settings_json.get("des_vars") if isinstance(settings_json, dict) else None
    return isinstance(des_vars, dict) and any(
        isinstance(name, str) and name.strip() for name in des_vars.keys()
    )


def _extract_stage2_roles_with_design_variables(tagging_json: Any) -> Set[str]:
    if not isinstance(tagging_json, dict):
        return set()
    stage2 = tagging_json.get("stage2")
    if not isinstance(stage2, dict):
        return set()
    roles = stage2.get("roles")
    if not isinstance(roles, list):
        return set()

    role_names: Set[str] = set()
    for role in roles:
        if not isinstance(role, dict):
            continue
        role_name = role.get("name")
        if not isinstance(role_name, str) or not role_name.strip():
            continue
        if _role_has_design_variables(role):
            role_names.add(role_name)
    return role_names


def _role_has_design_variables(role: Any) -> bool:
    if not isinstance(role, dict):
        return False
    substructures = role.get("substructures")
    if not isinstance(substructures, list):
        return False
    for sub in substructures:
        if not isinstance(sub, dict):
            continue
        variables = sub.get("variables")
        if not isinstance(variables, list):
            continue
        for variable in variables:
            if not isinstance(variable, dict):
                continue
            design_variables = variable.get("design_variables")
            if not isinstance(design_variables, list):
                continue
            if any(isinstance(name, str) and name.strip() for name in design_variables):
                return True
    return False


def _trim_tagging_for_prompt(tagging_json: Any) -> Any:
    if not isinstance(tagging_json, dict):
        return tagging_json
    return _drop_evidence_recursive(tagging_json)


def _drop_evidence_recursive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_evidence_recursive(item) for key, item in value.items() if key != "evidence"
        }
    if isinstance(value, list):
        return [_drop_evidence_recursive(item) for item in value]
    return value


def _extract_unowned_design_variables(tagging_json: Any, settings_json: Any) -> Set[str]:
    des_vars = settings_json.get("des_vars") if isinstance(settings_json, dict) else None
    if not isinstance(des_vars, dict):
        return set()
    return {
        name
        for name in des_vars.keys()
        if isinstance(name, str)
        and name.strip()
        and name not in _extract_tagged_design_variables(tagging_json)
    }


def _extract_tagged_design_variables(tagging_json: Any) -> Set[str]:
    if not isinstance(tagging_json, dict):
        return set()
    stage2 = tagging_json.get("stage2")
    if not isinstance(stage2, dict):
        return set()
    roles = stage2.get("roles")
    if not isinstance(roles, list):
        return set()

    names: Set[str] = set()
    for role in roles:
        if not isinstance(role, dict):
            continue
        substructures = role.get("substructures")
        if not isinstance(substructures, list):
            continue
        for sub in substructures:
            if not isinstance(sub, dict):
                continue
            vars_list = sub.get("variables")
            if not isinstance(vars_list, list):
                continue
            for item in vars_list:
                if not isinstance(item, dict):
                    continue
                design_variables = item.get("design_variables")
                if not isinstance(design_variables, list):
                    continue
                for name in design_variables:
                    if isinstance(name, str) and name.strip():
                        names.add(name)
    return names


def _extract_allowed_metrics(design_specs_json: Any) -> Set[str]:
    if not isinstance(design_specs_json, dict):
        raise ValueError("design specs must be a JSON object")

    specs = design_specs_json.get("performance_specs")
    if not isinstance(specs, list):
        raise ValueError("design_specs.performance_specs must be a JSON array")

    metrics = {
        item.get("name")
        for item in specs
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item.get("name", "").strip()
    }
    metrics = {name for name in metrics if isinstance(name, str)}
    if not metrics:
        raise ValueError("design_specs.performance_specs must contain at least one metric name")
    return metrics


def _objective_metric(design_specs_json: Any) -> str | None:
    if not isinstance(design_specs_json, dict):
        return None
    objective = design_specs_json.get("objective")
    if not isinstance(objective, dict):
        return None
    metric = objective.get("metric")
    if isinstance(metric, str) and metric.strip():
        return metric.strip()
    return None


def _hide_objective_metric_for_initialization(design_specs_json: Any) -> Any:
    if not isinstance(design_specs_json, dict):
        return design_specs_json
    objective_metric = _objective_metric(design_specs_json)
    if not objective_metric:
        return design_specs_json

    prompt_specs = dict(design_specs_json)
    prompt_specs["objective_hidden_until_feasible"] = {
        "reason": "Initialization should first seek feasible non-objective specs.",
    }
    prompt_specs.pop("objective", None)
    performance_specs = prompt_specs.get("performance_specs")
    if isinstance(performance_specs, list):
        prompt_specs["performance_specs"] = [
            item
            for item in performance_specs
            if not (isinstance(item, dict) and item.get("name") == objective_metric)
        ]
    return prompt_specs


def _hide_objective_metric_from_settings(settings_json: Any, design_specs_json: Any) -> Any:
    if not isinstance(settings_json, dict):
        return settings_json
    objective_metric = _objective_metric(design_specs_json)
    if not objective_metric:
        return settings_json

    prompt_settings = dict(settings_json)
    prompt_settings["objective_hidden_until_feasible"] = {
        "reason": "Initialization should first seek feasible non-objective specs.",
    }
    prompt_settings.pop("objective", None)
    outputs = prompt_settings.get("outputs")
    if isinstance(outputs, dict):
        prompt_settings["outputs"] = {
            name: value
            for name, value in outputs.items()
            if name != objective_metric and not is_operation_region_metric(name)
        }
    responses = prompt_settings.get("responses")
    if isinstance(responses, dict):
        prompt_settings["responses"] = {
            tb_name: [
                metric
                for metric in metrics
                if metric != objective_metric and not is_operation_region_metric(metric)
            ]
            if isinstance(metrics, list)
            else metrics
            for tb_name, metrics in responses.items()
        }
    return prompt_settings


def _load_prompt(filename: str) -> str:
    return read_text("prompts", "initialization", filename)


def _render_prompt(template: str, replacements: Dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered
