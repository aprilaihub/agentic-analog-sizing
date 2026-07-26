#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _clean_parameter(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return re.sub(r"\d+", "", value)


def clean_payload(payload: Any) -> tuple[Any, int, int]:
    if not isinstance(payload, dict):
        raise ValueError("Top-level JSON must be an object")

    facts = payload.get("facts")
    if not isinstance(facts, list):
        raise ValueError("JSON must contain a 'facts' array")

    parameter_updates = 0
    removed_evidence_iters = 0

    for item in facts:
        if not isinstance(item, dict):
            continue

        if "parameter" in item:
            before = item["parameter"]
            after = _clean_parameter(before)
            if before != after:
                item["parameter"] = after
                parameter_updates += 1

        if "evidence_iters" in item:
            item.pop("evidence_iters", None)
            removed_evidence_iters += 1

    return payload, parameter_updates, removed_evidence_iters


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove digits from facts[].parameter and delete facts[].evidence_iters."
    )
    parser.add_argument("json_path", help="Path to substruct_param_perf JSON file")
    args = parser.parse_args()

    json_path = Path(args.json_path).expanduser().resolve()
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    cleaned, parameter_updates, removed_evidence_iters = clean_payload(payload)
    json_path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(
        f"Updated {json_path}: parameter changes={parameter_updates}, "
        f"removed evidence_iters={removed_evidence_iters}"
    )


if __name__ == "__main__":
    main()
