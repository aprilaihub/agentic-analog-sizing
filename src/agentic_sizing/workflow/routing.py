from __future__ import annotations

import time
from typing import Dict, List

from ..core.models import SpecConstraint
from .state import AgenticSizingState


def _spec_satisfied(spec: SpecConstraint, perf_values: Dict[str, float]) -> bool:
    value = perf_values.get(spec.name)
    if value is None:
        return False

    if spec.relation == "min":
        return value >= spec.target
    if spec.relation == "max":
        return value <= spec.target
    tolerance = max(abs(spec.target) * 0.01, 1e-6)
    return (value - spec.target) <= tolerance


def find_unsatisfied_perfs(specs: List[SpecConstraint], perf_values: Dict[str, float]) -> List[str]:
    return [spec.name for spec in specs if not _spec_satisfied(spec, perf_values)]


def runtime_limit_reached(state: AgenticSizingState) -> bool:
    max_runtime_seconds = float(state.get("max_runtime_seconds", 0.0) or 0.0)
    if max_runtime_seconds <= 0.0:
        return False
    started_at = state.get("run_started_at_unix_s")
    if started_at is None:
        return False
    return (time.time() - float(started_at)) >= max_runtime_seconds


def route_after_select(state: AgenticSizingState) -> str:
    if runtime_limit_reached(state):
        return "terminate"
    if state.get("iteration", 0) >= state.get("max_iter", 500):
        return "terminate"

    unsatisfied = state.get("unsatisfied_perfs", [])
    feasible_objective_phase = bool(state.get("continue_after_specs", False)) and not unsatisfied
    if (
        state.get("stagnation_count", 0) >= state.get("max_stagnation", 5)
        and not feasible_objective_phase
    ):
        return "terminate"
    if not unsatisfied:
        if feasible_objective_phase:
            return "planner_dispatch"
        return "terminate"
    return "planner_dispatch"


def route_after_check(state: AgenticSizingState) -> str:
    if runtime_limit_reached(state):
        return "terminate"
    if state.get("iteration", 0) >= state.get("max_iter", 500):
        return "terminate"
    unsatisfied = state.get("unsatisfied_perfs", [])
    feasible_objective_phase = bool(state.get("continue_after_specs", False)) and not unsatisfied
    if (
        state.get("stagnation_count", 0) >= state.get("max_stagnation", 5)
        and not feasible_objective_phase
    ):
        return "terminate"

    if state.get("force_simulation_commit", False):
        return "simulate_commit"
    return "select_unsat_perf"
