from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Set

from ..llm.contract import (
    LLMMessage,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    StructuredLLMClient,
)
from ..llm.factory import create_structured_client
from ..resources import read_text
from .schemas import (
    STEP1_SCHEMA,
    STEP2_SCHEMA,
    SchemaValidationError,
    validate_final_output,
    validate_step1_payload,
    validate_step2_payload,
)


class TaggingPipelineError(RuntimeError):
    """Raised when two-stage tagging fails after retries."""


_DEVICE_INSTANCE_RE = re.compile(r"^([^\s(]+)\s*\(")


def run_two_stage_tagging(
    input_path: str,
    output_path: str | None = None,
    model: str = "gpt-5.2",
    max_retries: int = 2,
    temperature: float = 0.1,
    reasoning_effort: Literal["low", "medium", "high"] = "low",
    llm_client: StructuredLLMClient | None = None,
) -> Dict[str, Any]:
    netlist_file = Path(input_path).expanduser().resolve()
    if not netlist_file.exists():
        raise FileNotFoundError(f"Input netlist not found: {netlist_file}")

    netlist_text = netlist_file.read_text(encoding="utf-8")
    subckt_name = _extract_subckt_name(netlist_text)
    netlist_devices = _extract_device_names(netlist_text)
    netlist_device_set = set(netlist_devices)

    step1_prompt = _render_prompt(
        _load_prompt("step1_functional_role_partitioning.md"),
        {"netlist": netlist_text},
    )

    client = llm_client or create_structured_client(provider="openai")

    stage1_payload = _run_with_retries(
        stage_name="step1",
        max_retries=max_retries,
        producer=lambda: _extract_object_payload(
            client.generate_structured(
                StructuredGenerationRequest(
                    provider="openai",
                    model=model,
                    messages=[
                        LLMMessage(
                            role="system",
                            content="You are an analog circuit analysis assistant. Return strict JSON only.",
                        ),
                        LLMMessage(role="user", content=step1_prompt),
                    ],
                    schema_name="functional_role_partitioning",
                    schema=STEP1_SCHEMA,
                    strict=True,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            )
        ),
        validator=lambda payload: _validate_stage1(payload, netlist_device_set),
    )

    stage2_prompt = _render_prompt(
        _load_prompt("step2_substructure_tagging.md"),
        {
            "netlist": netlist_text,
            "functional_partition_json": json.dumps(stage1_payload, indent=2, ensure_ascii=True),
        },
    )

    stage2_payload = _run_with_retries(
        stage_name="step2",
        max_retries=max_retries,
        producer=lambda: _extract_object_payload(
            client.generate_structured(
                StructuredGenerationRequest(
                    provider="openai",
                    model=model,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "You are an analog circuit analysis assistant. Return strict JSON only and keep "
                                "devices consistent with the provided functional partition."
                            ),
                        ),
                        LLMMessage(role="user", content=stage2_prompt),
                    ],
                    schema_name="substructure_tagging",
                    schema=STEP2_SCHEMA,
                    strict=True,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            )
        ),
        validator=lambda payload: _validate_stage2(payload, stage1_payload, netlist_device_set),
    )

    validation_report = _build_validation_report(stage1_payload, stage2_payload, netlist_device_set)

    final_output: Dict[str, Any] = {
        "schema_version": "1.1.0",
        "tool": {
            "name": "two_stage_tagger",
            "provider": "openai",
            "model": model,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "input": {
            "netlist_path": str(netlist_file),
            "subckt_name": subckt_name,
            "device_count": len(netlist_devices),
        },
        "stage1": stage1_payload,
        "stage2": stage2_payload,
        "validation": validation_report,
    }

    final_output = validate_final_output(final_output)

    target_path = _resolve_output_path(netlist_file, output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(final_output, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    return final_output


def _run_with_retries(
    stage_name: str,
    max_retries: int,
    producer: Callable[[], Dict[str, Any]],
    validator: Callable[[Dict[str, Any]], Dict[str, Any]],
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
            if _is_connection_like_error(exc):
                time.sleep(min(2.0, 0.5 * (attempt + 1)))

    detail = _format_exception_chain(last_error) if last_error is not None else "unknown error"
    hint = ""
    if last_error is not None and _is_connection_like_error(last_error):
        hint = (
            " Check OPENAI_API_KEY, outbound network access, proxy/TLS settings, and whether the "
            "active Python environment can reach the OpenAI Responses API."
        )
    raise TaggingPipelineError(
        f"{stage_name} failed after {max_retries + 1} attempts: {detail}.{hint}"
    ) from last_error


def _format_exception_chain(exc: Exception | None) -> str:
    if exc is None:
        return "unknown error"

    parts: List[str] = []
    seen: Set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = type(current).__name__
        message = str(current).strip()
        parts.append(f"{name}: {message}" if message else name)
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


def _is_connection_like_error(exc: Exception) -> bool:
    normalized = _format_exception_chain(exc).lower()
    keywords = (
        "connection error",
        "connection reset",
        "apiconnectionerror",
        "connecterror",
        "connecttimeout",
        "readtimeout",
        "timeout",
        "temporarily unavailable",
        "server disconnected",
        "dns",
        "name resolution",
        "ssl",
        "tls",
        "network",
    )
    return any(keyword in normalized for keyword in keywords)


def _extract_object_payload(result: StructuredGenerationResult) -> Dict[str, Any]:
    payload = result.output_json
    if not isinstance(payload, dict):
        raise RuntimeError("Structured response must be a JSON object.")
    return payload


def _validate_stage1(payload: Dict[str, Any], netlist_devices: Set[str]) -> Dict[str, Any]:
    data = validate_step1_payload(payload)

    device_counts: Dict[str, int] = {}
    unknown_devices: Set[str] = set()
    for role in data["functional_roles"]:
        external_role = _is_external_testbench_role(role["name"])
        for device in role["devices"]:
            device_counts[device] = device_counts.get(device, 0) + 1
            if device not in netlist_devices and not external_role:
                unknown_devices.add(device)

    duplicates = sorted(device for device, count in device_counts.items() if count > 1)
    if duplicates:
        raise SchemaValidationError(f"Step1 contains duplicated device assignments: {duplicates}")
    if unknown_devices:
        raise SchemaValidationError(f"Step1 contains unknown devices: {sorted(unknown_devices)}")

    return data


def _validate_stage2(
    payload: Dict[str, Any],
    stage1_payload: Dict[str, Any],
    netlist_devices: Set[str],
) -> Dict[str, Any]:
    data = validate_step2_payload(payload)
    report = _build_validation_report(stage1_payload, data, netlist_devices)

    if not report["stage2_role_membership_ok"]:
        raise SchemaValidationError("Step2 role membership check failed.")
    if not report["all_devices_known"]:
        raise SchemaValidationError(f"Step2 contains unknown devices: {report['unknown_devices']}")

    return data


def _build_validation_report(
    stage1_payload: Dict[str, Any],
    stage2_payload: Dict[str, Any],
    netlist_devices: Set[str],
) -> Dict[str, Any]:
    stage1_roles = stage1_payload["functional_roles"]
    stage2_roles = stage2_payload["roles"]

    role_to_devices: Dict[str, Set[str]] = {}
    device_counts: Dict[str, int] = {}
    stage1_devices_seen: Set[str] = set()

    for role in stage1_roles:
        role_name = role["name"]
        role_devices = set(role["devices"])
        role_to_devices[role_name] = role_devices
        for device in role["devices"]:
            stage1_devices_seen.add(device)
            device_counts[device] = device_counts.get(device, 0) + 1

    duplicate_devices = sorted(device for device, count in device_counts.items() if count > 1)

    stage2_role_membership_ok = True
    stage2_devices_seen: Set[str] = set()
    for role in stage2_roles:
        role_name = role["name"]
        allowed = role_to_devices.get(role_name)
        if allowed is None:
            stage2_role_membership_ok = False
            for sub in role["substructures"]:
                stage2_devices_seen.update(sub["devices"])
            continue

        for sub in role["substructures"]:
            sub_devices = set(sub["devices"])
            stage2_devices_seen.update(sub_devices)
            if not sub_devices.issubset(allowed):
                stage2_role_membership_ok = False

    external_devices = {
        device
        for role in stage1_roles
        if _is_external_testbench_role(role["name"])
        for device in role["devices"]
    }
    all_tagged_devices = stage1_devices_seen.union(stage2_devices_seen) - external_devices
    unknown_devices = sorted(
        device for device in all_tagged_devices if device not in netlist_devices
    )

    unassigned_devices = sorted(
        device for device in netlist_devices if device not in stage1_devices_seen
    )

    return {
        "stage1_unique_assignment_ok": len(duplicate_devices) == 0,
        "stage2_role_membership_ok": stage2_role_membership_ok,
        "all_devices_known": len(unknown_devices) == 0,
        "duplicate_devices": duplicate_devices,
        "unknown_devices": unknown_devices,
        "unassigned_devices": unassigned_devices,
    }


def _is_external_testbench_role(role_name: str) -> bool:
    normalized = role_name.lower()
    return "testbench" in normalized or "measurement" in normalized


def _resolve_output_path(input_file: Path, output_path: str | None) -> Path:
    if output_path:
        return Path(output_path).expanduser().resolve()
    return input_file.with_suffix(".json")


def _load_prompt(filename: str) -> str:
    return read_text("prompts", "tagging", filename)


def _render_prompt(template: str, replacements: Dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def _extract_subckt_name(netlist_text: str) -> str:
    for line in netlist_text.splitlines():
        match = re.match(r"^\s*subckt\s+(\S+)", line, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _extract_device_names(netlist_text: str) -> List[str]:
    devices: List[str] = []
    for line in netlist_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        match = _DEVICE_INSTANCE_RE.match(stripped)
        if match:
            devices.append(match.group(1))
    return devices
