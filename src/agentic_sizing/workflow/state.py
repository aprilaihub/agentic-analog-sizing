from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal

try:
    from typing import TypedDict
except ImportError:  # pragma: no cover - Python <3.8 fallback
    from typing_extensions import TypedDict

from ..core.models import (
    FunctionalRole,
    IterationRecord,
    PlannerTask,
    SpecConstraint,
    WorkerProposal,
)


class KBPaths(TypedDict):
    planner_index: str
    worker_template: str
    episodes_log: str


class AgenticSizingState(TypedDict, total=False):
    netlist_path: str
    case_name: str
    specs: List[SpecConstraint]
    current_design_vars: Dict[str, float]
    current_perfs: Dict[str, float]
    operation_region_summary: Dict[str, Any]
    predicted_perfs: Dict[str, float]
    best_known_design_vars: Dict[str, float]
    best_known_perfs: Dict[str, float]
    best_known_iteration: int
    objective_metric: str
    objective_sense: Literal["min", "max"]
    last_anchor_status: Dict[str, Any]
    design_var_order: List[str]
    perf_order: List[str]
    unsatisfied_perfs: List[str]
    functional_roles: List[FunctionalRole]
    current_perf: str
    current_role: FunctionalRole
    planner_task: PlannerTask
    worker_proposal: WorkerProposal
    iteration: int
    max_iter: int
    stagnation_count: int
    max_stagnation: int
    max_runtime_seconds: float
    history: List[IterationRecord]
    termination_reason: str
    kb_paths: KBPaths
    initialize_mode: Literal["real", "mock"]
    simulation_backend: Literal["real", "mock"]
    simulation_record_path: str
    llm_usage_record_path: str
    enable_kb_input: bool
    enable_heuristics: bool
    initial_sample_count: int
    continue_after_specs: bool
    planner_worker_iter: int
    max_planner_worker_iter: int
    force_simulation_commit: bool
    llm_client: Any
    simulation_adapter: Any
    run_started_at_unix_s: float
    run_started_at_utc: str


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path(os.getenv("AGENTIC_SIZING_PROJECT_ROOT", Path.cwd())).expanduser().resolve()


def resolve_agentic_path(path_text: str) -> str:
    path_obj = Path(path_text).expanduser()
    if path_obj.is_absolute():
        return str(path_obj.resolve())
    return str((PROJECT_ROOT / path_obj).resolve())


def default_specs() -> List[SpecConstraint]:
    return [
        SpecConstraint(name="gain", target=60.0, relation="min", weight=1.0),
        SpecConstraint(name="ugb", target=1.0e7, relation="min", weight=1.0),
        SpecConstraint(name="pm", target=60.0, relation="min", weight=1.0),
        SpecConstraint(name="power", target=2.0, relation="max", weight=1.0),
    ]


def default_design_vars() -> Dict[str, float]:
    return {
        "gm1": 1.2,
        "gm2": 1.0,
        "rout": 8.0,
        "cc": 1.0,
        "ibias": 1.0,
    }


def default_functional_roles() -> List[FunctionalRole]:
    return [
        FunctionalRole(
            role_id="input_stage",
            role_name="Input Transconductor",
            subblocks=["differential_pair", "tail_current_source"],
            design_variables=["gm1", "ibias"],
            affectable_perfs=["gain", "ugb", "power"],
        ),
        FunctionalRole(
            role_id="load_stage",
            role_name="Active Load / Output Stage",
            subblocks=["active_load", "output_node"],
            design_variables=["gm2", "rout"],
            affectable_perfs=["gain", "ugb", "power"],
        ),
        FunctionalRole(
            role_id="compensation",
            role_name="Compensation Network",
            subblocks=["miller_cap", "zero_control_path"],
            design_variables=["cc"],
            affectable_perfs=["pm", "ugb"],
        ),
    ]


def create_initial_state(
    netlist_path: str,
    kb_root: str,
    max_iter: int = 400,
    max_stagnation: int = 500,
    max_runtime_seconds: float = 0.0,
    max_planner_worker_iter: int = 2,
    initialize_mode: Literal["real", "mock"] = "real",
    simulation_backend: Literal["real", "mock"] = "real",
    simulation_record_path: str = "output/simulation_record.json",
    enable_kb_input: bool = True,
    enable_heuristics: bool = True,
    initial_sample_count: int = 1,
    continue_after_specs: bool = False,
    simulation_adapter: Any = None,
    llm_client: Any = None,
) -> AgenticSizingState:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    original_path = Path(simulation_record_path)
    new_filename = f"{timestamp}_{original_path.name}"
    simulation_record_path = str(original_path.parent / new_filename)
    resolved_simulation_record_path = resolve_agentic_path(simulation_record_path)
    llm_usage_record_path = str(
        Path(resolved_simulation_record_path).with_name(
            f"{Path(resolved_simulation_record_path).stem}_llm_usage.jsonl"
        )
    )
    resolved_kb_root = resolve_agentic_path(kb_root)
    kb_paths: KBPaths = {
        "planner_index": os.path.join(resolved_kb_root, "planner", "planner_index.json"),
        "worker_template": os.path.join(resolved_kb_root, "workers", "template_role.json"),
        "episodes_log": os.path.join(os.path.dirname(resolved_kb_root), "episodes.jsonl"),
    }

    return AgenticSizingState(
        netlist_path=netlist_path,
        case_name="",
        specs=default_specs(),
        current_design_vars=default_design_vars(),
        current_perfs={},
        operation_region_summary={},
        predicted_perfs={},
        objective_metric="power",
        objective_sense="min",
        design_var_order=[],
        perf_order=[],
        unsatisfied_perfs=[],
        current_perf="",
        iteration=0,
        max_iter=max_iter,
        stagnation_count=0,
        max_stagnation=max_stagnation,
        max_runtime_seconds=max(0.0, float(max_runtime_seconds)),
        planner_worker_iter=0,
        max_planner_worker_iter=max_planner_worker_iter,
        force_simulation_commit=False,
        history=[],
        termination_reason="",
        kb_paths=kb_paths,
        initialize_mode=initialize_mode,
        simulation_backend=simulation_backend,
        simulation_record_path=resolved_simulation_record_path,
        llm_usage_record_path=llm_usage_record_path,
        enable_kb_input=bool(enable_kb_input),
        enable_heuristics=bool(enable_heuristics),
        initial_sample_count=max(1, int(initial_sample_count)),
        continue_after_specs=bool(continue_after_specs),
        simulation_adapter=simulation_adapter,
        llm_client=llm_client,
        run_started_at_unix_s=now.timestamp(),
        run_started_at_utc=now.isoformat(),
    )
