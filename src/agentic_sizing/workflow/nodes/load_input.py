from __future__ import annotations

from ...core.models import make_iteration_record
from ..state import (
    AgenticSizingState,
    default_design_vars,
    default_functional_roles,
    default_specs,
)


def load_input(state: AgenticSizingState) -> AgenticSizingState:
    functional_roles = list(state.get("functional_roles") or default_functional_roles())

    history = list(state.get("history", []))
    history.append(
        make_iteration_record(
            iteration=state.get("iteration", 0),
            node="load_input",
            decision="initialize_state",
            details={
                "netlist_path": state.get("netlist_path", ""),
                "role_count": len(functional_roles),
            },
        )
    )

    updates: AgenticSizingState = {
        "specs": state.get("specs", default_specs()),
        "current_design_vars": state.get("current_design_vars", default_design_vars()),
        "functional_roles": functional_roles,
        "history": history,
        "termination_reason": state.get("termination_reason", ""),
    }
    return updates
