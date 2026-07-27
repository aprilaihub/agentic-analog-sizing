from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal

RelationType = Literal["min", "max", "target"]


@dataclass
class SpecConstraint:
    name: str
    target: float
    relation: RelationType
    weight: float = 1.0


@dataclass
class FunctionalRole:
    role_id: str
    role_name: str
    subblocks: List[str] = field(default_factory=list)
    design_variables: List[str] = field(default_factory=list)
    affectable_perfs: List[str] = field(default_factory=list)


@dataclass
class PlannerTask:
    target_metric: str
    selected_role_name: str
    worker_instruction: str
    selection_rationale: str = ""
    focus_kb_evidence: List[str] = field(default_factory=list)
    unsatisfied_metrics: List[str] = field(default_factory=list)


@dataclass
class WorkerProposal:
    role_id: str
    target_metric: str
    updated_design_vars: Dict[str, float]
    predicted_performances: Dict[str, float]
    rationale: str = ""


@dataclass
class IterationRecord:
    iteration: int
    node: str
    timestamp: str
    decision: str
    details: Dict[str, Any] = field(default_factory=dict)


def make_iteration_record(
    iteration: int,
    node: str,
    decision: str,
    details: Dict[str, Any] | None = None,
) -> IterationRecord:
    return IterationRecord(
        iteration=iteration,
        node=node,
        timestamp=datetime.now(timezone.utc).isoformat(),
        decision=decision,
        details=details or {},
    )


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {key: to_jsonable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value
