from __future__ import annotations

from ...core.models import WorkerProposal, make_iteration_record
from ...iteration import run_iterative_worker
from ...iteration.context import resolve_case_name
from ..state import AgenticSizingState


def worker_propose(state: AgenticSizingState) -> AgenticSizingState:
    role = state.get("current_role")
    task = state.get("planner_task")

    if role is None or task is None:
        raise RuntimeError("worker_propose requires current_role and planner_task in state")

    case_name = resolve_case_name(state.get("case_name", ""), state.get("netlist_path", ""))

    return _run_worker(state, case_name)


def _run_worker(state: AgenticSizingState, case_name: str) -> AgenticSizingState:
    role = state.get("current_role")
    task = state.get("planner_task")
    if role is None or task is None:
        raise RuntimeError("worker_propose requires current_role and planner_task in state")

    worker_result = run_iterative_worker(
        case_name=case_name,
        role_name=task.selected_role_name,
        target_metric=task.target_metric,
        worker_instruction=task.worker_instruction,
        simulation_record_path=state.get("simulation_record_path", ""),
        current_design_vars=state.get("current_design_vars", {}),
        current_predicted_perfs=state.get("predicted_perfs") or state.get("current_perfs"),
        current_operation_region_summary=state.get("operation_region_summary"),
        enable_kb_input=bool(state.get("enable_kb_input", True)),
        enable_heuristics=bool(state.get("enable_heuristics", True)),
        anchor_status=state.get("last_anchor_status"),
        provider="openai",
        model="gpt-5.2",
        reasoning_effort="high",
        max_retries=2,
        temperature=0.5,
        llm_client=state.get("llm_client"),
    )

    updates = {item["name"]: float(item["value"]) for item in worker_result["updated_design_vars"]}
    predicted_performances = {
        item["name"]: float(item["value"]) for item in worker_result["predicted_performances"]
    }

    proposal = WorkerProposal(
        role_id=role.role_id,
        target_metric=task.target_metric,
        updated_design_vars=updates,
        predicted_performances=predicted_performances,
        rationale=worker_result["rationale"],
    )

    history = list(state.get("history", []))
    history.append(
        make_iteration_record(
            iteration=state.get("iteration", 0),
            node="worker_propose",
            decision="llm_worker_generated_update",
            details={
                "case_name": case_name,
                "role_id": proposal.role_id,
                "target_metric": proposal.target_metric,
                "updated_design_vars": proposal.updated_design_vars,
                "predicted_performances": proposal.predicted_performances,
                "candidate_count_sampled": int(worker_result.get("candidate_count_sampled", 1)),
            },
        )
    )

    return {
        "worker_proposal": proposal,
        "history": history,
    }
