from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from .schemas import validate_simulation_record, validate_simulation_record_file


def append_simulation_record(
    simulation_record_path: str,
    *,
    parameters: Iterable[float],
    performance: Iterable[float],
    iteration: int | None = None,
    cost_time_s: float | None = None,
) -> dict:
    path = Path(simulation_record_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    records = load_simulation_records(str(path))
    last_iter = records[-1]["iter"] if records else 0

    if iteration is None or iteration <= last_iter:
        next_iter = last_iter + 1
    else:
        next_iter = iteration

    raw_record = {
        "iter": int(next_iter),
        "parameters": [float(x) for x in parameters],
        "performance": [float(x) for x in performance],
    }
    if cost_time_s is not None:
        raw_record["cost_time_s"] = float(cost_time_s)

    new_record = validate_simulation_record(raw_record)

    records.append(new_record)
    _write_records(path, records)
    write_runtime_summary(str(path))
    return new_record


def load_simulation_records(simulation_record_path: str) -> List[dict]:
    path = Path(simulation_record_path).expanduser().resolve()
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_simulation_record_file(payload)


def _write_records(path: Path, records: List[dict]) -> None:
    path.write_text(json.dumps(records, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def get_runtime_summary_path(simulation_record_path: str) -> str:
    path = Path(simulation_record_path).expanduser().resolve()
    return str(path.with_name(f"{path.stem}_runtime_summary{path.suffix}"))


def write_runtime_summary(
    simulation_record_path: str,
    *,
    run_started_at_unix_s: float | None = None,
    run_started_at_utc: str | None = None,
    run_finished_at_unix_s: float | None = None,
    run_finished_at_utc: str | None = None,
    termination_reason: str | None = None,
) -> dict:
    path = Path(simulation_record_path).expanduser().resolve()
    summary_path = Path(get_runtime_summary_path(str(path)))
    records = load_simulation_records(str(path))

    timed_records = [record for record in records if "cost_time_s" in record]
    total_recorded_simulation_runtime_s = sum(
        float(record["cost_time_s"]) for record in timed_records
    )
    llm_usage = load_llm_usage_summary(str(path))

    summary = {
        "record_path": str(path),
        "llm_usage_record_path": llm_usage["path"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "iterations": len(records),
        "timed_iterations": len(timed_records),
        "untimed_iterations": len(records) - len(timed_records),
        "total_recorded_simulation_runtime_s": float(total_recorded_simulation_runtime_s),
        "llm_usage": llm_usage["summary"],
    }

    if run_started_at_unix_s is not None:
        summary["run_started_at_unix_s"] = float(run_started_at_unix_s)
    if run_started_at_utc is not None:
        summary["run_started_at_utc"] = str(run_started_at_utc)
    if run_finished_at_unix_s is not None:
        summary["run_finished_at_unix_s"] = float(run_finished_at_unix_s)
    if run_finished_at_utc is not None:
        summary["run_finished_at_utc"] = str(run_finished_at_utc)
    if run_started_at_unix_s is not None and run_finished_at_unix_s is not None:
        summary["total_wall_clock_runtime_s"] = float(
            run_finished_at_unix_s - run_started_at_unix_s
        )
    if termination_reason is not None:
        summary["termination_reason"] = str(termination_reason)

    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return summary


def get_llm_usage_record_path(simulation_record_path: str) -> str:
    path = Path(simulation_record_path).expanduser().resolve()
    return str(path.with_name(f"{path.stem}_llm_usage.jsonl"))


def load_llm_usage_summary(simulation_record_path: str) -> dict:
    usage_path = Path(get_llm_usage_record_path(simulation_record_path))
    summary = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "by_schema": {},
        "by_model": {},
    }
    if not usage_path.exists():
        return {"path": str(usage_path), "summary": summary}

    for line in usage_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = record.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        schema_name = str(record.get("schema_name", "unknown") or "unknown")
        model = str(record.get("model", "unknown") or "unknown")
        _accumulate_usage(summary, usage)
        _accumulate_usage(
            summary["by_schema"].setdefault(schema_name, _empty_usage_bucket()), usage
        )
        _accumulate_usage(summary["by_model"].setdefault(model, _empty_usage_bucket()), usage)

    return {"path": str(usage_path), "summary": summary}


def _empty_usage_bucket() -> dict:
    return {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
    }


def _accumulate_usage(bucket: dict, usage: dict) -> None:
    bucket["calls"] = int(bucket.get("calls", 0)) + 1
    for key in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens"):
        value = usage.get(key, 0)
        if isinstance(value, int):
            bucket[key] = int(bucket.get(key, 0)) + value
