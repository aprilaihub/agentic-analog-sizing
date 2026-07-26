from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from .improving_designs import generate_improving_designs
from .merge import merge_kb_files  # <-- still used
from .pipeline import run_kb_fact_extraction


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run 4-step LLM KB and transferable-heuristic extraction."
    )
    parser.add_argument("--settings", required=True, help="Path to settings JSON")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--improving-designs", help="Path to an existing improving designs JSON")
    source.add_argument(
        "--simulation-record",
        help="Simulation record JSON to preprocess into a constraint-first improving trace",
    )
    parser.add_argument(
        "--improving-designs-output",
        help="Generated trace path (default: beside settings as <case>_improving_designs.json)",
    )
    parser.add_argument(
        "--max-improving-designs",
        type=int,
        default=20,
        help="Maximum points retained from a generated improving trace (default: 20)",
    )
    parser.add_argument("--tagging", required=True, help="Path to tagging JSON")
    parser.add_argument("--output-dir", help="Directory for 3 KB output files")
    parser.add_argument("--output-prefix", help="Filename prefix for output files")
    parser.add_argument(
        "--output",
        help=(
            "Deprecated alias from single-file mode. Parsed as output dir + prefix "
            "(e.g. /tmp/5t_ota_KB.json -> /tmp + 5t_ota)."
        ),
    )
    parser.add_argument("--provider", default="openai", help="LLM provider name")
    parser.add_argument("--model", default="gpt-5.2", help="Model name")
    parser.add_argument("--max-retries", type=int, default=2, help="Retries after initial failure")
    parser.add_argument("--temperature", type=float, default=0.5, help="Sampling temperature")
    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        default="high",
        help="Reasoning effort passed to model API",
    )

    # merge options
    parser.add_argument(
        "--merge-existing",
        nargs="*",
        help="Optional existing KB files (or globs) to merge after generation",
    )
    parser.add_argument(
        "--keep-conflicts",
        action="store_true",
        help="Keep conflicting influence-strength facts when merging",
    )
    parser.add_argument(
        "--merged-output-name",
        default=None,
        help=(
            "Optional merged output filename (default: <output-prefix>_merged_kb.json) "
            "written into --output-dir."
        ),
    )

    # NEW: global prefix for the 3 generated global KB view files
    parser.add_argument(
        "--global-prefix",
        default="global_",
        help="Prefix for global KB view files (default: global_).",
    )
    parser.add_argument(
        "--heuristics-output-dir",
        default=None,
        help="Critical heuristic directory (default: output/critical_heuristics)",
    )
    parser.add_argument(
        "--disable-heuristic-extraction",
        action="store_true",
        help="Run only the original three KB extraction stages",
    )

    args = parser.parse_args()

    improving_designs_path = args.improving_designs
    if args.simulation_record:
        settings_path = Path(args.settings).expanduser().resolve()
        generated_path = (
            Path(args.improving_designs_output).expanduser().resolve()
            if args.improving_designs_output
            else settings_path.with_name(
                f"{settings_path.stem.removesuffix('_settings')}_improving_designs.json"
            )
        )
        try:
            trace = generate_improving_designs(
                settings_path=str(settings_path),
                simulation_record_path=args.simulation_record,
                output_path=str(generated_path),
                max_points=args.max_improving_designs,
            )
        except Exception as exc:
            print(f"Improving-design generation failed: {exc}", file=sys.stderr)
            return 1
        improving_designs_path = str(generated_path)
        print(f"Generated {len(trace)} improving designs: {generated_path}")

    output_dir = args.output_dir
    output_prefix = args.output_prefix
    if args.output:
        if output_dir or output_prefix:
            parser.error("--output cannot be combined with --output-dir or --output-prefix")
        output_dir, output_prefix = _parse_deprecated_output_alias(args.output)
        print(
            "[deprecated] --output is deprecated. Use --output-dir and --output-prefix.",
            file=sys.stderr,
        )

    try:
        result = run_kb_fact_extraction(
            settings_path=args.settings,
            improving_designs_path=improving_designs_path,
            tagging_path=args.tagging,
            output_dir=output_dir,
            output_prefix=output_prefix,
            provider=args.provider,
            model=args.model,
            max_retries=args.max_retries,
            temperature=args.temperature,
            reasoning_effort=args.reasoning_effort,
            generate_heuristics=not args.disable_heuristic_extraction,
            heuristics_output_dir=args.heuristics_output_dir,
        )
    except Exception as exc:
        print(f"KB extraction failed: {exc}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------
    # GLOBAL merge step (optional): generate new global_*.json files
    # ------------------------------------------------------------
    merged_count: int | None = None
    written_global_views: dict[str, str] = {}
    merged_output_path: str | None = None

    if args.merge_existing:
        # Expand user-provided globs + literal paths
        merge_inputs: list[str] = []
        for item in args.merge_existing:
            matches = glob.glob(item)
            if matches:
                merge_inputs.extend(matches)
            else:
                merge_inputs.append(item)

        # Also include the KB files just generated (paths returned by pipeline)
        generated_output_files = result.get("output_files", {})
        if isinstance(generated_output_files, dict):
            generated_files = list(generated_output_files.values())
        else:
            generated_files = list(generated_output_files)
        all_inputs = merge_inputs + generated_files

        merged_facts = merge_kb_files(
            input_paths=all_inputs,
            omit_conflicts=(not args.keep_conflicts),
        )
        merged_count = len(merged_facts)

        # Decide output location
        out_dir: Path
        if output_dir:
            out_dir = Path(output_dir).expanduser().resolve()
        else:
            # infer from first generated file if possible
            if generated_files:
                out_dir = Path(generated_files[0]).expanduser().resolve().parent
            else:
                out_dir = Path(".").resolve()

        out_dir.mkdir(parents=True, exist_ok=True)

        # Optional single merged file (kept for backward compatibility)
        if not output_prefix:
            output_prefix = "kb"
        merged_name = args.merged_output_name or f"{output_prefix}_merged_kb.json"
        merged_output_path = str(out_dir / merged_name)
        with open(merged_output_path, "w", encoding="utf-8") as f:
            json.dump(
                _drop_verbose_fact_fields({"facts": merged_facts}), f, indent=2, ensure_ascii=True
            )
            f.write("\n")

        # Split merged facts into 3 "views" by type
        by_type: dict[str, list[dict]] = {
            "perf_perf_tradeoff": [],
            "substruct_param_perf": [],
            "role_perf": [],
        }
        for fact in merged_facts:
            if isinstance(fact, dict):
                t = fact.get("type")
                if t in by_type:
                    by_type[t].append(fact)

        # Write global view files (new files, not overwriting case-specific ones)
        gp = args.global_prefix or "global_"
        global_files = {
            "perf_tradeoff": out_dir / f"{gp}kb_perf_tradeoff.json",
            "substruct_param_perf": out_dir / f"{gp}kb_substruct_param_perf.json",
            "role_perf": out_dir / f"{gp}kb_role_perf.json",
        }
        type_mapping = {
            "perf_tradeoff": "perf_perf_tradeoff",
            "substruct_param_perf": "substruct_param_perf",
            "role_perf": "role_perf",
        }

        for view_key, path in global_files.items():
            fact_type = type_mapping[view_key]
            payload = _drop_verbose_fact_fields({"facts": by_type[fact_type]})
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            written_global_views[view_key] = str(path)

    # ------------------------------------------------------------
    # Print summary JSON
    # ------------------------------------------------------------
    summary: dict[str, object] = {
        "provider": args.provider,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "counts": {
            "perf_tradeoff": len(result.get("perf_tradeoff", {}).get("facts", [])),
            "substruct_param_perf": len(result.get("substruct_param_perf", {}).get("facts", [])),
            "role_perf": len(result.get("role_perf", {}).get("facts", [])),
        },
        "output_files": result.get("output_files", []),
        "critical_heuristic_count": len(result.get("critical_heuristics", [])),
        "critical_heuristic_files": result.get("critical_heuristic_files", {}),
    }

    if merged_count is not None:
        summary["merged_output_file"] = merged_output_path
        summary["merged_fact_count"] = merged_count
        summary["merge_conflicts_omitted"] = not args.keep_conflicts

    if written_global_views:
        summary["global_kb_files"] = written_global_views
        summary["global_prefix"] = args.global_prefix

    print(json.dumps(summary, ensure_ascii=True))
    return 0


def _drop_verbose_fact_fields(payload: dict[str, object]) -> dict[str, object]:
    facts = payload.get("facts")
    if not isinstance(facts, list):
        return payload

    cleaned_facts: list[object] = []
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


def _parse_deprecated_output_alias(output: str) -> tuple[str, str]:
    output_path = Path(output).expanduser().resolve()
    stem = output_path.stem
    lowered = stem.lower()

    if lowered.endswith("_kb"):
        prefix = stem[:-3]
    elif lowered.endswith("_kb_facts"):
        prefix = stem[:-9]
    else:
        prefix = stem

    prefix = prefix.strip()
    if not prefix:
        raise ValueError(f"Cannot infer output prefix from deprecated --output path: {output_path}")

    return str(output_path.parent), prefix


if __name__ == "__main__":
    raise SystemExit(main())
