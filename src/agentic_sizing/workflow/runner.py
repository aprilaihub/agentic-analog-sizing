from __future__ import annotations

import argparse
import json
from typing import Literal

from ..core.models import to_jsonable
from ..initialization.record_store import get_runtime_summary_path
from .graph import compile_graph
from .state import create_initial_state


def run_demo(
    netlist_path: str,
    kb_root: str,
    max_iter: int,
    max_stagnation: int,
    max_runtime_seconds: float = 0.0,
    max_planner_worker_iter: int = 2,
    mode: Literal["real", "mock"] = "real",
    simulation_record_path: str = "output/simulation_record.json",
    enable_kb_input: bool = True,
    enable_heuristics: bool = True,
    initial_sample_count: int = 1,
    continue_after_specs: bool = False,
    simulation_adapter=None,
    llm_client=None,
) -> dict:
    app = compile_graph()
    initial_state = create_initial_state(
        netlist_path=netlist_path,
        kb_root=kb_root,
        max_iter=max_iter,
        max_stagnation=max_stagnation,
        max_runtime_seconds=max_runtime_seconds,
        max_planner_worker_iter=max_planner_worker_iter,
        initialize_mode=mode,
        simulation_backend=mode,
        simulation_record_path=simulation_record_path,
        enable_kb_input=enable_kb_input,
        enable_heuristics=enable_heuristics,
        initial_sample_count=initial_sample_count,
        continue_after_specs=continue_after_specs,
        simulation_adapter=simulation_adapter,
        llm_client=llm_client,
    )
    return app.invoke(initial_state, config={"recursion_limit": 5000})


def main() -> None:
    parser = argparse.ArgumentParser(description="Run agentic sizing state-machine demo.")
    parser.add_argument("--netlist", required=True, help="Path to input netlist")
    parser.add_argument(
        "--kb-root", required=True, help="Path to KB root (for example /.../ESSAB/reference/kb)"
    )
    parser.add_argument("--max-iter", type=int, default=400)
    parser.add_argument("--max-stagnation", type=int, default=500)
    parser.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=0.0,
        help="Wall-clock runtime limit in seconds. Use 0 to disable.",
    )
    parser.add_argument(
        "--max-planner-worker-iter",
        type=int,
        default=2,
        help="Maximum planner-worker proposal rounds before forcing one simulation commit.",
    )
    parser.add_argument(
        "--mode",
        choices=["real", "mock"],
        default="real",
        help="Use real or mock initialization and simulation together.",
    )
    parser.add_argument(
        "--simulation-record-path",
        default="output/simulation_record.json",
        help="Path for simulation records JSON (iter/parameters/performance).",
    )
    parser.add_argument(
        "--disable-kb-input",
        action="store_true",
        help="Disable KB facts as planner/worker input for ablation studies.",
    )
    parser.add_argument(
        "--disable-heuristics",
        action="store_true",
        help="Disable critical heuristics as planner/worker input independently of other KB facts.",
    )
    parser.add_argument(
        "--initial-sample-count",
        type=int,
        default=1,
        help="Number of initialization candidates to simulate before selecting the starting anchor.",
    )
    parser.add_argument(
        "--continue-after-specs",
        action="store_true",
        help=(
            "Keep optimizing the objective after all specs are met. In this mode, feasible "
            "iterations do not count as stagnation; the run stops by max_iter or normal "
            "stagnation before feasibility."
        ),
    )
    parser.add_argument("--show-history", action="store_true")
    args = parser.parse_args()

    final_state = run_demo(
        netlist_path=args.netlist,
        kb_root=args.kb_root,
        max_iter=args.max_iter,
        max_stagnation=args.max_stagnation,
        max_runtime_seconds=args.max_runtime_seconds,
        max_planner_worker_iter=args.max_planner_worker_iter,
        mode=args.mode,
        simulation_record_path=args.simulation_record_path,
        enable_kb_input=not args.disable_kb_input,
        enable_heuristics=not args.disable_heuristics,
        initial_sample_count=args.initial_sample_count,
        continue_after_specs=args.continue_after_specs,
    )

    output = {
        "termination_reason": final_state.get("termination_reason", ""),
        "iteration": final_state.get("iteration", 0),
        "unsatisfied_perfs": final_state.get("unsatisfied_perfs", []),
        "current_perfs": final_state.get("current_perfs", {}),
        "current_design_vars": final_state.get("current_design_vars", {}),
        "best_known_perfs": final_state.get("best_known_perfs", {}),
        "best_known_design_vars": final_state.get("best_known_design_vars", {}),
        "objective_metric": final_state.get("objective_metric", ""),
        "objective_sense": final_state.get("objective_sense", ""),
        "case_name": final_state.get("case_name", ""),
        "max_runtime_seconds": final_state.get("max_runtime_seconds", 0.0),
        "simulation_record_path": final_state.get("simulation_record_path", ""),
        "llm_usage_record_path": final_state.get("llm_usage_record_path", ""),
        "runtime_summary_path": get_runtime_summary_path(
            final_state.get("simulation_record_path", "")
        ),
    }
    if args.show_history:
        output["history"] = final_state.get("history", [])

    print(json.dumps(to_jsonable(output), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
