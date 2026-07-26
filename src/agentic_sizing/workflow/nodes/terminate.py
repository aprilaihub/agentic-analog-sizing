from __future__ import annotations

import time
from datetime import datetime, timezone

from ...core.models import make_iteration_record
from ...initialization.record_store import get_runtime_summary_path, write_runtime_summary
from ...iteration.run_role_perf import remove_run_role_perf_summary
from ..routing import runtime_limit_reached
from ..state import AgenticSizingState


def terminate(state: AgenticSizingState) -> AgenticSizingState:
    reason = state.get("termination_reason", "")
    if not reason:
        if runtime_limit_reached(state):
            reason = "time_limit_reached"
        elif state.get("iteration", 0) >= state.get("max_iter", 400):
            reason = "max_iter_reached"
        elif state.get("stagnation_count", 0) >= state.get("max_stagnation", 5):
            reason = "stagnation_reached"
        elif not state.get("unsatisfied_perfs", []):
            reason = "all_specs_met"
        else:
            reason = "terminated_without_reason"

    history = list(state.get("history", []))
    history.append(
        make_iteration_record(
            iteration=state.get("iteration", 0),
            node="terminate",
            decision="stop_execution",
            details={
                "termination_reason": reason,
                "runtime_summary_path": get_runtime_summary_path(
                    state.get("simulation_record_path", "")
                ),
                "llm_usage_record_path": state.get("llm_usage_record_path", ""),
            },
        )
    )

    simulation_record_path = state.get("simulation_record_path", "")
    if simulation_record_path:
        write_runtime_summary(
            simulation_record_path,
            run_started_at_unix_s=state.get("run_started_at_unix_s"),
            run_started_at_utc=state.get("run_started_at_utc"),
            run_finished_at_unix_s=time.time(),
            run_finished_at_utc=datetime.now(timezone.utc).isoformat(),
            termination_reason=reason,
        )
        remove_run_role_perf_summary(simulation_record_path)

    return {
        "termination_reason": reason,
        "history": history,
    }
