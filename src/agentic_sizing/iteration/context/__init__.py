"""Context construction and data helpers for iterative sizing."""

from .builders import (
    build_planner_context,
    build_worker_context,
    resolve_case_name,
    resolve_case_paths,
)
from .data import (
    compute_weighted_violations,
    evaluate_unsatisfied_metrics,
    extract_stage1_role_names,
    filter_substruct_param_perf_facts,
    load_json_file,
)
from .errors import IterativeSizingContextError

__all__ = [
    "build_planner_context",
    "build_worker_context",
    "compute_weighted_violations",
    "evaluate_unsatisfied_metrics",
    "extract_stage1_role_names",
    "filter_substruct_param_perf_facts",
    "load_json_file",
    "IterativeSizingContextError",
    "resolve_case_name",
    "resolve_case_paths",
]
