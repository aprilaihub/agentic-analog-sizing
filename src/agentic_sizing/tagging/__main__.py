from __future__ import annotations

import argparse
import json
import sys

from .pipeline import run_two_stage_tagging


def main() -> int:
    parser = argparse.ArgumentParser(description="Run two-stage structural tagging.")
    parser.add_argument("--input", required=True, help="Path to transistor-level netlist")
    parser.add_argument("--output", help="Path to output JSON file")
    parser.add_argument("--model", default="gpt-5.2", help="OpenAI model name")
    parser.add_argument(
        "--max-retries", type=int, default=2, help="Retries per stage after initial failure"
    )
    parser.add_argument("--temperature", type=float, default=0.5, help="Sampling temperature")
    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        default="high",
        help="Reasoning effort passed to model API",
    )
    args = parser.parse_args()

    try:
        result = run_two_stage_tagging(
            input_path=args.input,
            output_path=args.output,
            model=args.model,
            max_retries=args.max_retries,
            temperature=args.temperature,
            reasoning_effort=args.reasoning_effort,
        )
    except Exception as exc:
        print(f"Tagging failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "model": result["tool"]["model"],
                "netlist_path": result["input"]["netlist_path"],
                "device_count": result["input"]["device_count"],
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
