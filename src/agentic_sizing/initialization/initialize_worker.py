from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Sequence, Set

from ..core.llm_metric_ranges import annotate_design_specs_for_llm, annotate_settings_for_llm
from ..core.operation_region import is_operation_region_metric
from ..kb.critical_heuristics import retrieve_critical_heuristics
from ..kb.interpreter import summarize_substruct_param_perf_facts
from ..llm.contract import LLMMessage, StructuredGenerationRequest, StructuredLLMClient
from ..llm.factory import create_structured_client
from ..resources import read_text
from .schemas import (
    WORKER_OUTPUT_SCHEMA,
    InitializeSchemaValidationError,
    validate_worker_payload,
)


class InitializeWorkerError(RuntimeError):
    """Raised when initialize worker fails after retries."""


SYNTHETIC_CONTROL_ROLE = "Testbench and bias controls"


def run_initialize_worker(
    role_name: str,
    worker_instruction: str,
    settings_path: str,
    tagging_path: str,
    design_specs_path: str,
    prior_context: Any,
    kb_substruct_param_perf_path: str | None = None,
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
    role_name = role_name.strip()
    if not role_name:
        raise ValueError("role_name must be non-empty")
    if not worker_instruction.strip():
        raise ValueError("worker_instruction must be non-empty")

    settings_file = _resolve_existing_file(settings_path, "settings")
    tagging_file = _resolve_existing_file(tagging_path, "tagging")
    design_specs_file = _resolve_existing_file(design_specs_path, "design specs")
    kb_substruct_param_perf_file = (
        _resolve_existing_file(kb_substruct_param_perf_path, "kb substruct param perf")
        if kb_substruct_param_perf_path and enable_kb_input
        else None
    )

    settings_json = _load_json_file(settings_file, "settings")
    tagging_json = _load_json_file(tagging_file, "tagging")
    design_specs_json = _load_json_file(design_specs_file, "design specs")
    prompt_design_specs_json = _hide_objective_metric_for_initialization(design_specs_json)
    prompt_settings_json = _hide_objective_metric_from_settings(settings_json, design_specs_json)
    prompt_design_specs_json = annotate_design_specs_for_llm(prompt_design_specs_json)
    prompt_settings_json = annotate_settings_for_llm(prompt_settings_json)
    case_name = _infer_case_name_from_settings_path(settings_file)
    kb_substruct_param_perf_json = (
        _load_json_file(kb_substruct_param_perf_file, "kb substruct param perf")
        if kb_substruct_param_perf_file is not None
        else {"facts": []}
    )
    kb_substruct_param_perf_summary = (
        summarize_substruct_param_perf_facts(
            kb_substruct_param_perf_json,
            target_metrics=_extract_allowed_metrics(prompt_design_specs_json),
        )
        if enable_kb_input
        else []
    )
    critical_heuristics = (
        retrieve_critical_heuristics(
            case_name=case_name,
            target_metrics=sorted(_extract_allowed_metrics(prompt_design_specs_json)),
            scope="worker",
        )
        if enable_kb_input and enable_heuristics
        else []
    )

    role_design_variables = _extract_role_design_variables(tagging_json, settings_json, role_name)
    if not role_design_variables:
        raise ValueError(f"No design variables found for role '{role_name}' in tagging output")
    variable_bounds = _extract_variable_bounds(settings_json, role_design_variables)

    prompt = _render_prompt(
        _load_prompt("initialize_worker.md"),
        {
            "role_name": role_name,
            "worker_instruction": worker_instruction,
            "role_design_variables_json": json.dumps(
                role_design_variables, indent=2, ensure_ascii=True
            ),
            "variable_bounds_json": json.dumps(variable_bounds, indent=2, ensure_ascii=True),
            "design_specs_json": json.dumps(prompt_design_specs_json, indent=2, ensure_ascii=True),
            "kb_substruct_param_perf_summary_json": json.dumps(
                kb_substruct_param_perf_summary,
                indent=2,
                ensure_ascii=True,
            ),
            "kb_substruct_param_perf_summary_block": (
                "Interpreted KB substructure-parameter-performance hints:\n"
                f"{json.dumps(kb_substruct_param_perf_summary, indent=2, ensure_ascii=True)}"
                if enable_kb_input
                else ""
            ),
            "critical_heuristics_json": json.dumps(
                critical_heuristics,
                indent=2,
                ensure_ascii=True,
            ),
            "critical_heuristics_block": (
                f"- Retrieved critical heuristics for this case:\n{json.dumps(critical_heuristics, indent=2, ensure_ascii=True)}"
                if enable_kb_input and enable_heuristics
                else ""
            ),
            "prior_context_json": json.dumps(prior_context, indent=2, ensure_ascii=True),
            "settings_json": json.dumps(prompt_settings_json, indent=2, ensure_ascii=True),
        },
    )

    client = llm_client or create_structured_client(provider=provider, api_key=api_key)

    return _run_with_retries(
        stage_name=f"initialize_worker[{role_name}]",
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
                                "You are an analog IC initialize worker. Return strict JSON only and assign "
                                "valid in-range values for all role variables."
                            ),
                        ),
                        LLMMessage(role="user", content=prompt),
                    ],
                    schema_name="initialize_worker_output",
                    schema=WORKER_OUTPUT_SCHEMA,
                    strict=True,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            )
        ),
        validator=lambda payload: validate_worker_payload(
            payload,
            role_name=role_name,
            allowed_variables=set(role_design_variables),
            variable_bounds=variable_bounds,
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

    raise InitializeWorkerError(
        f"{stage_name} failed after {max_retries + 1} attempts: {last_error}"
    ) from last_error


def _extract_payload(result: Any) -> Dict[str, Any]:
    payload = result.output_json
    if not isinstance(payload, dict):
        raise InitializeSchemaValidationError("initialize worker output must be a JSON object.")
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


def _extract_role_design_variables(
    tagging_json: Any, settings_json: Any, role_name: str
) -> List[str]:
    if not isinstance(tagging_json, dict):
        raise ValueError("tagging must be a JSON object")
    stage2 = tagging_json.get("stage2")
    if not isinstance(stage2, dict):
        raise ValueError("tagging.stage2 must be a JSON object")
    roles = stage2.get("roles")
    if not isinstance(roles, list):
        raise ValueError("tagging.stage2.roles must be a JSON array")

    variables: List[str] = []
    seen: Set[str] = set()
    found_role = False

    for role in roles:
        if not isinstance(role, dict):
            continue
        if role.get("name") != role_name:
            continue
        found_role = True
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
                    if isinstance(name, str) and name.strip() and name not in seen:
                        seen.add(name)
                        variables.append(name)

    if not found_role:
        if role_name == SYNTHETIC_CONTROL_ROLE:
            return _extract_unowned_design_variables(tagging_json, settings_json)
        raise ValueError(f"role '{role_name}' not found in tagging.stage2.roles")
    return variables


def _extract_unowned_design_variables(tagging_json: Any, settings_json: Any) -> List[str]:
    des_vars = settings_json.get("des_vars") if isinstance(settings_json, dict) else None
    if not isinstance(des_vars, dict):
        return []
    tagged = set(_extract_tagged_design_variables(tagging_json))
    return [
        name
        for name in des_vars.keys()
        if isinstance(name, str) and name.strip() and name not in tagged
    ]


def _extract_allowed_metrics(design_specs_json: Any) -> Set[str]:
    if not isinstance(design_specs_json, dict):
        raise ValueError("design specs must be a JSON object")
    performance_specs = design_specs_json.get("performance_specs")
    if not isinstance(performance_specs, list):
        raise ValueError("design_specs.performance_specs must be a JSON array")
    return {
        str(item.get("name"))
        for item in performance_specs
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item.get("name", "").strip()
    }


def _extract_tagged_design_variables(tagging_json: Any) -> List[str]:
    if not isinstance(tagging_json, dict):
        return []
    stage2 = tagging_json.get("stage2")
    if not isinstance(stage2, dict):
        return []
    roles = stage2.get("roles")
    if not isinstance(roles, list):
        return []

    variables: List[str] = []
    seen: Set[str] = set()
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
                    if isinstance(name, str) and name.strip() and name not in seen:
                        seen.add(name)
                        variables.append(name)
    return variables


def _extract_variable_bounds(
    settings_json: Any,
    variable_names: Iterable[str],
) -> Dict[str, Sequence[float]]:
    if not isinstance(settings_json, dict):
        raise ValueError("settings must be a JSON object")
    des_vars = settings_json.get("des_vars")
    if not isinstance(des_vars, dict):
        raise ValueError("settings.des_vars must be a JSON object")

    bounds: Dict[str, Sequence[float]] = {}
    for name in variable_names:
        if name not in des_vars:
            raise ValueError(f"settings.des_vars missing variable '{name}'")
        raw = des_vars[name]
        if not isinstance(raw, list) or len(raw) not in {2, 3}:
            raise ValueError(f"settings.des_vars.{name} must be [min,max] or [min,max,is_int]")
        lower = float(raw[0])
        upper = float(raw[1])
        is_int = bool(raw[2]) if len(raw) == 3 else False
        bounds[name] = [lower, upper, 1.0 if is_int else 0.0]
    return bounds


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
