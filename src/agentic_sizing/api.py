"""Stable public API for agentic sizing workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .llm.contract import StructuredLLMClient
from .simulator import SimulationAdapter


@dataclass(frozen=True, slots=True)
class RunConfig:
    netlist_path: str | Path
    kb_root: str | Path
    output_dir: str | Path = "output"
    max_iter: int = 400
    max_stagnation: int = 500
    max_runtime_seconds: float = 0.0
    max_planner_worker_iter: int = 2
    mode: Literal["real", "mock"] = "real"
    record_filename: str = "simulation_record.json"
    enable_kb_input: bool = True
    enable_heuristics: bool = True
    initial_sample_count: int = 1
    continue_after_specs: bool = False

    @property
    def simulation_record_path(self) -> Path:
        return Path(self.output_dir).expanduser() / self.record_filename


@dataclass(frozen=True, slots=True)
class RunResult:
    termination_reason: str
    iteration: int
    case_name: str
    current_perfs: dict[str, float] = field(default_factory=dict)
    current_design_vars: dict[str, float] = field(default_factory=dict)
    best_known_perfs: dict[str, float] = field(default_factory=dict)
    best_known_design_vars: dict[str, float] = field(default_factory=dict)
    unsatisfied_perfs: list[str] = field(default_factory=list)
    simulation_record_path: str = ""
    llm_usage_record_path: str = ""
    raw_state: dict[str, Any] = field(default_factory=dict, repr=False)


def run_sizing(
    config: RunConfig,
    *,
    simulator: SimulationAdapter | None = None,
    llm_client: StructuredLLMClient | None = None,
) -> RunResult:
    """Run a sizing workflow with optional caller-provided adapters."""
    from .workflow.runner import run_demo

    state = run_demo(
        netlist_path=str(Path(config.netlist_path).expanduser()),
        kb_root=str(Path(config.kb_root).expanduser()),
        max_iter=config.max_iter,
        max_stagnation=config.max_stagnation,
        max_runtime_seconds=config.max_runtime_seconds,
        max_planner_worker_iter=config.max_planner_worker_iter,
        mode=config.mode,
        simulation_record_path=str(config.simulation_record_path),
        enable_kb_input=config.enable_kb_input,
        enable_heuristics=config.enable_heuristics,
        initial_sample_count=config.initial_sample_count,
        continue_after_specs=config.continue_after_specs,
        simulation_adapter=simulator,
        llm_client=llm_client,
    )
    return RunResult(
        termination_reason=str(state.get("termination_reason", "")),
        iteration=int(state.get("iteration", 0)),
        case_name=str(state.get("case_name", "")),
        current_perfs=dict(state.get("current_perfs", {})),
        current_design_vars=dict(state.get("current_design_vars", {})),
        best_known_perfs=dict(state.get("best_known_perfs", {})),
        best_known_design_vars=dict(state.get("best_known_design_vars", {})),
        unsatisfied_perfs=list(state.get("unsatisfied_perfs", [])),
        simulation_record_path=str(state.get("simulation_record_path", "")),
        llm_usage_record_path=str(state.get("llm_usage_record_path", "")),
        raw_state=dict(state),
    )
