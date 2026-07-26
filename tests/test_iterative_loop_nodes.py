from __future__ import annotations

import importlib
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.core.models import (
    FunctionalRole,
    PlannerTask,
    SpecConstraint,
    WorkerProposal,
)
from agentic_sizing.workflow.nodes.apply_update import apply_update
from agentic_sizing.workflow.nodes.check_completion import check_completion
from agentic_sizing.workflow.nodes.simulate_commit import simulate_commit
from agentic_sizing.workflow.routing import route_after_check

planner_dispatch_module = importlib.import_module("agentic_sizing.workflow.nodes.planner_dispatch")
simulate_commit_module = importlib.import_module("agentic_sizing.workflow.nodes.simulate_commit")
worker_propose_module = importlib.import_module("agentic_sizing.workflow.nodes.worker_propose")

planner_dispatch = planner_dispatch_module.planner_dispatch
worker_propose = worker_propose_module.worker_propose


class TestIterativeLoopNodes(unittest.TestCase):
    def test_apply_update_scope_guard_and_counter(self) -> None:
        state = {
            "current_role": FunctionalRole(
                role_id="bias",
                role_name="Bias network",
                design_variables=["l1", "w1"],
            ),
            "current_design_vars": {"l1": 1.0, "w1": 2.0, "l2": 3.0},
            "predicted_perfs": {"cmrr": 70.0, "power": 5.0},
            "specs": [
                SpecConstraint(name="cmrr", target=80.0, relation="min"),
                SpecConstraint(name="power", target=4.0, relation="max"),
            ],
            "unsatisfied_perfs": ["cmrr", "power"],
            "stagnation_count": 5,
            "planner_worker_iter": 0,
            "iteration": 1,
            "worker_proposal": WorkerProposal(
                role_id="bias",
                target_metric="cmrr",
                updated_design_vars={"l1": 1.1, "l2": 9.9},
                predicted_performances={"cmrr": 82.0, "power": 3.5},
                rationale="test",
            ),
        }

        updates = apply_update(state)
        self.assertEqual(updates["current_design_vars"]["l1"], 1.1)
        self.assertEqual(updates["current_design_vars"]["l2"], 3.0)
        self.assertEqual(updates["planner_worker_iter"], 1)
        self.assertEqual(updates["predicted_perfs"]["cmrr"], 82.0)

    def test_apply_update_does_not_revert_before_simulation(self) -> None:
        state = {
            "current_role": FunctionalRole(
                role_id="bias",
                role_name="Bias network",
                design_variables=["l1", "w1"],
            ),
            "current_design_vars": {"l1": 1.0, "w1": 2.0},
            "predicted_perfs": {"cmrr": 82.0, "power": 3.5},
            "best_known_design_vars": {"l1": 1.0, "w1": 2.0},
            "best_known_perfs": {"cmrr": 82.0, "power": 3.5},
            "specs": [
                SpecConstraint(name="cmrr", target=80.0, relation="min"),
                SpecConstraint(name="power", target=4.0, relation="max"),
            ],
            "unsatisfied_perfs": [],
            "stagnation_count": 0,
            "planner_worker_iter": 0,
            "iteration": 1,
            "worker_proposal": WorkerProposal(
                role_id="bias",
                target_metric="cmrr",
                updated_design_vars={"l1": 1.4},
                predicted_performances={"cmrr": 78.0, "power": 4.5},
                rationale="worse proposal",
            ),
        }

        updates = apply_update(state)
        self.assertEqual(updates["current_design_vars"], {"l1": 1.4, "w1": 2.0})
        self.assertEqual(updates["predicted_perfs"], {"cmrr": 78.0, "power": 4.5})
        self.assertEqual(updates["unsatisfied_perfs"], ["cmrr", "power"])

    @patch.object(simulate_commit_module, "append_simulation_record")
    @patch.object(simulate_commit_module.MockSimulationAdapter, "simulate")
    def test_simulate_commit_keeps_worse_candidate_live_without_reverting_to_anchor(
        self,
        mock_simulate,  # type: ignore[no-untyped-def]
        mock_append,  # type: ignore[no-untyped-def]
    ) -> None:
        mock_simulate.return_value = {"cmrr": 78.0, "power": 4.5}
        mock_append.return_value = {"iter": 2}

        state = {
            "current_design_vars": {"l1": 1.4, "w1": 2.0},
            "current_perfs": {"cmrr": 82.0, "power": 3.5},
            "predicted_perfs": {"cmrr": 78.0, "power": 4.5},
            "best_known_design_vars": {"l1": 1.0, "w1": 2.0},
            "best_known_perfs": {"cmrr": 82.0, "power": 3.5},
            "best_known_iteration": 1,
            "specs": [
                SpecConstraint(name="cmrr", target=80.0, relation="min"),
                SpecConstraint(name="power", target=4.0, relation="max"),
            ],
            "simulation_backend": "mock",
            "initialize_mode": "mock",
            "case_name": "5t_ota",
            "simulation_record_path": "output/simulation_record.json",
            "design_var_order": ["l1", "w1"],
            "perf_order": ["cmrr", "power"],
            "iteration": 1,
            "history": [],
        }

        updates = simulate_commit(state)
        self.assertEqual(updates["current_design_vars"], {"l1": 1.4, "w1": 2.0})
        self.assertEqual(updates["current_perfs"], {"cmrr": 78.0, "power": 4.5})
        self.assertEqual(updates["predicted_perfs"], {"cmrr": 78.0, "power": 4.5})
        self.assertEqual(updates["best_known_design_vars"], {"l1": 1.0, "w1": 2.0})
        self.assertEqual(updates["best_known_perfs"], {"cmrr": 82.0, "power": 3.5})
        self.assertEqual(updates["unsatisfied_perfs"], ["cmrr", "power"])
        self.assertFalse(updates["last_anchor_status"]["reverted"])
        self.assertEqual(updates["last_anchor_status"]["action"], "kept_diverse_commit")

    @patch.object(simulate_commit_module, "append_simulation_record")
    @patch.object(simulate_commit_module.MockSimulationAdapter, "simulate")
    def test_simulate_commit_keeps_diverse_commit_in_early_phase_when_not_severely_worse(
        self,
        mock_simulate,  # type: ignore[no-untyped-def]
        mock_append,  # type: ignore[no-untyped-def]
    ) -> None:
        mock_simulate.return_value = {"cmrr": 62.0, "power": 3.5, "psrr": 55.0}
        mock_append.return_value = {"iter": 6}

        state = {
            "current_design_vars": {"l1": 1.4, "w1": 2.0},
            "current_perfs": {"cmrr": 65.0, "power": 3.5, "psrr": 58.0},
            "predicted_perfs": {"cmrr": 62.0, "power": 3.5, "psrr": 55.0},
            "best_known_design_vars": {"l1": 1.0, "w1": 2.0},
            "best_known_perfs": {"cmrr": 65.0, "power": 3.5, "psrr": 58.0},
            "best_known_iteration": 1,
            "specs": [
                SpecConstraint(name="cmrr", target=80.0, relation="min"),
                SpecConstraint(name="power", target=4.0, relation="max"),
                SpecConstraint(name="psrr", target=60.0, relation="min"),
                SpecConstraint(name="adm", target=70.0, relation="min"),
            ],
            "simulation_backend": "mock",
            "initialize_mode": "mock",
            "case_name": "5t_ota",
            "simulation_record_path": "output/simulation_record.json",
            "design_var_order": ["l1", "w1"],
            "perf_order": ["cmrr", "power", "psrr"],
            "iteration": 5,
            "history": [],
        }

        updates = simulate_commit(state)
        self.assertEqual(updates["current_design_vars"], {"l1": 1.4, "w1": 2.0})
        self.assertEqual(updates["current_perfs"], {"cmrr": 62.0, "power": 3.5, "psrr": 55.0})
        self.assertEqual(updates["predicted_perfs"], {"cmrr": 62.0, "power": 3.5, "psrr": 55.0})
        self.assertFalse(updates["last_anchor_status"]["reverted"])
        self.assertEqual(updates["last_anchor_status"]["action"], "kept_diverse_commit")

    @patch.object(simulate_commit_module, "append_simulation_record")
    @patch.object(simulate_commit_module.MockSimulationAdapter, "simulate")
    def test_simulate_commit_does_not_skip_legacy_reverted_anchor_state(
        self,
        mock_simulate,  # type: ignore[no-untyped-def]
        mock_append,  # type: ignore[no-untyped-def]
    ) -> None:
        mock_simulate.return_value = {"cmrr": 81.0, "power": 3.6}
        mock_append.return_value = {"iter": 3}

        state = {
            "current_design_vars": {"l1": 1.0, "w1": 2.0},
            "current_perfs": {"cmrr": 82.0, "power": 3.5},
            "predicted_perfs": {"cmrr": 78.0, "power": 4.5},
            "best_known_design_vars": {"l1": 1.0, "w1": 2.0},
            "best_known_perfs": {"cmrr": 82.0, "power": 3.5},
            "best_known_iteration": 1,
            "last_anchor_status": {
                "action": "reverted_to_anchor",
                "best_known_iteration": 1,
                "latest_record_iter": 2,
                "reverted": True,
                "message": "reverted",
            },
            "specs": [
                SpecConstraint(name="cmrr", target=80.0, relation="min"),
                SpecConstraint(name="power", target=4.0, relation="max"),
            ],
            "simulation_backend": "mock",
            "initialize_mode": "mock",
            "case_name": "5t_ota",
            "simulation_record_path": "output/simulation_record.json",
            "design_var_order": ["l1", "w1"],
            "perf_order": ["cmrr", "power"],
            "iteration": 2,
            "history": [],
        }

        updates = simulate_commit(state)
        self.assertEqual(updates["current_design_vars"], {"l1": 1.0, "w1": 2.0})
        self.assertEqual(updates["current_perfs"], {"cmrr": 81.0, "power": 3.6})
        self.assertEqual(updates["predicted_perfs"], {"cmrr": 81.0, "power": 3.6})
        self.assertEqual(updates["planner_worker_iter"], 0)
        self.assertFalse(updates["force_simulation_commit"])
        mock_simulate.assert_called_once()
        mock_append.assert_called_once()

    def test_check_completion_force_commit_on_worker_budget(self) -> None:
        state = {
            "predicted_perfs": {"cmrr": 70.0, "power": 5.0},
            "specs": [
                SpecConstraint(name="cmrr", target=80.0, relation="min"),
                SpecConstraint(name="power", target=4.0, relation="max"),
            ],
            "planner_worker_iter": 10,
            "max_planner_worker_iter": 10,
            "iteration": 1,
            "stagnation_count": 0,
            "max_iter": 20,
            "max_stagnation": 5,
            "history": [],
        }
        updates = check_completion(state)
        self.assertTrue(updates["force_simulation_commit"])
        self.assertEqual(updates["unsatisfied_perfs"], ["cmrr", "power"])

    def test_route_after_check_uses_force_flag(self) -> None:
        self.assertEqual(
            route_after_check(
                {
                    "iteration": 1,
                    "max_iter": 20,
                    "stagnation_count": 0,
                    "max_stagnation": 5,
                    "force_simulation_commit": True,
                }
            ),
            "simulate_commit",
        )
        self.assertEqual(
            route_after_check(
                {
                    "iteration": 1,
                    "max_iter": 20,
                    "stagnation_count": 0,
                    "max_stagnation": 5,
                    "force_simulation_commit": False,
                }
            ),
            "select_unsat_perf",
        )

    @patch.object(planner_dispatch_module, "run_iterative_planner")
    def test_planner_dispatch_calls_iterative_planner(self, mock_planner):  # type: ignore[no-untyped-def]
        mock_planner.return_value = {
            "state_action": "continue_current",
            "target_metric": "cmrr",
            "selected_role_name": "Main signal path",
            "worker_instruction": "Increase gm impact for cmrr.",
            "selection_rationale": "best role",
            "recovery_rationale": "Continue from the current design.",
            "focus_kb_evidence": ["fact-a"],
            "unsatisfied_metrics": ["cmrr"],
        }

        state = {
            "netlist_path": "input/tagging/5t_ota",
            "case_name": "5t_ota",
            "simulation_record_path": "output/simulation_record.json",
            "predicted_perfs": {"cmrr": 70.0},
            "current_perfs": {"cmrr": 70.0},
            "current_perf": "cmrr",
            "functional_roles": [
                FunctionalRole(
                    role_id="main_signal_path",
                    role_name="Main signal path",
                    design_variables=["l2", "w2", "l3", "w3"],
                )
            ],
            "iteration": 1,
            "history": [],
        }

        updates = planner_dispatch(state)
        self.assertEqual(updates["current_perf"], "cmrr")
        self.assertEqual(updates["current_role"].role_name, "Main signal path")
        self.assertEqual(updates["planner_task"].target_metric, "cmrr")

    @patch.object(planner_dispatch_module, "run_iterative_planner")
    def test_planner_dispatch_applies_llm_requested_best_known_revert(self, mock_planner):  # type: ignore[no-untyped-def]
        mock_planner.return_value = {
            "state_action": "revert_to_best_known",
            "target_metric": "cmrr",
            "selected_role_name": "Main signal path",
            "worker_instruction": "Recover cmrr from the best-known point.",
            "selection_rationale": "Current trend is worse than the best-known point.",
            "recovery_rationale": "Recent steps increased weighted violation, so recover the anchor.",
            "focus_kb_evidence": ["local trend: weighted violation worsened"],
            "unsatisfied_metrics": ["cmrr", "power"],
        }

        state = {
            "netlist_path": "input/tagging/5t_ota",
            "case_name": "5t_ota",
            "simulation_record_path": "output/simulation_record.json",
            "current_design_vars": {"l1": 1.4, "w1": 2.0},
            "current_perfs": {"cmrr": 70.0, "power": 5.0},
            "predicted_perfs": {"cmrr": 70.0, "power": 5.0},
            "best_known_design_vars": {"l1": 1.0, "w1": 2.0},
            "best_known_perfs": {"cmrr": 82.0, "power": 3.5},
            "best_known_iteration": 1,
            "specs": [
                SpecConstraint(name="cmrr", target=80.0, relation="min"),
                SpecConstraint(name="power", target=4.0, relation="max"),
            ],
            "functional_roles": [
                FunctionalRole(
                    role_id="main_signal_path",
                    role_name="Main signal path",
                    design_variables=["l1", "w1"],
                )
            ],
            "iteration": 4,
            "history": [],
        }

        updates = planner_dispatch(state)
        self.assertEqual(updates["current_design_vars"], {"l1": 1.0, "w1": 2.0})
        self.assertEqual(updates["current_perfs"], {"cmrr": 82.0, "power": 3.5})
        self.assertEqual(updates["predicted_perfs"], {"cmrr": 82.0, "power": 3.5})
        self.assertEqual(updates["unsatisfied_perfs"], [])
        self.assertTrue(updates["last_anchor_status"]["reverted"])
        self.assertEqual(updates["last_anchor_status"]["action"], "llm_reverted_to_best_known")

    @patch.object(planner_dispatch_module, "run_iterative_planner")
    def test_planner_dispatch_rejects_revert_when_anchor_is_not_better(self, mock_planner):  # type: ignore[no-untyped-def]
        mock_planner.return_value = {
            "state_action": "revert_to_best_known",
            "target_metric": "cmrr",
            "selected_role_name": "Main signal path",
            "worker_instruction": "Try main path adjustment.",
            "selection_rationale": "Planner requested a revert.",
            "recovery_rationale": "Attempt revert, but guard should reject it.",
            "focus_kb_evidence": ["local trend: no clear anchor advantage"],
            "unsatisfied_metrics": ["cmrr"],
        }

        state = {
            "netlist_path": "input/tagging/5t_ota",
            "case_name": "5t_ota",
            "simulation_record_path": "output/simulation_record.json",
            "current_design_vars": {"l1": 1.4, "w1": 2.0},
            "current_perfs": {"cmrr": 82.0, "power": 3.5},
            "predicted_perfs": {"cmrr": 82.0, "power": 3.5},
            "best_known_design_vars": {"l1": 1.0, "w1": 2.0},
            "best_known_perfs": {"cmrr": 80.0, "power": 4.0},
            "best_known_iteration": 1,
            "specs": [
                SpecConstraint(name="cmrr", target=80.0, relation="min"),
                SpecConstraint(name="power", target=4.0, relation="max"),
            ],
            "functional_roles": [
                FunctionalRole(
                    role_id="main_signal_path",
                    role_name="Main signal path",
                    design_variables=["l1", "w1"],
                )
            ],
            "iteration": 4,
            "history": [],
        }

        updates = planner_dispatch(state)
        self.assertNotIn("current_design_vars", updates)
        self.assertEqual(updates["unsatisfied_perfs"], ["cmrr"])

    @patch.object(worker_propose_module, "run_iterative_worker")
    def test_worker_propose_calls_iterative_worker(self, mock_worker):  # type: ignore[no-untyped-def]
        mock_worker.return_value = {
            "role_name": "Main signal path",
            "target_metric": "cmrr",
            "updated_design_vars": [
                {"name": "l2", "value": 1.2e-06, "reason": "reason"},
                {"name": "l3", "value": 1.1e-06, "reason": "reason"},
                {"name": "w2", "value": 3.2e-05, "reason": "reason"},
                {"name": "w3", "value": 2.8e-05, "reason": "reason"},
            ],
            "predicted_performances": [
                {"name": "cmrr", "value": 82.0, "reason": "reason"},
                {"name": "power", "value": 3.8e-06, "reason": "reason"},
            ],
            "rationale": "worker rationale",
        }

        state = {
            "case_name": "5t_ota",
            "netlist_path": "input/tagging/5t_ota",
            "simulation_record_path": "output/simulation_record.json",
            "current_design_vars": {"l2": 1.0e-06, "w2": 2.0e-05, "l3": 1.0e-06, "w3": 2.0e-05},
            "predicted_perfs": {"cmrr": 70.0, "power": 4.5e-06},
            "current_perfs": {"cmrr": 70.0, "power": 4.5e-06},
            "current_role": FunctionalRole(
                role_id="main_signal_path",
                role_name="Main signal path",
                design_variables=["l2", "w2", "l3", "w3"],
            ),
            "planner_task": PlannerTask(
                target_metric="cmrr",
                selected_role_name="Main signal path",
                worker_instruction="Improve cmrr.",
                selection_rationale="",
            ),
            "iteration": 1,
            "history": [],
        }

        updates = worker_propose(state)
        proposal = updates["worker_proposal"]
        self.assertEqual(proposal.target_metric, "cmrr")
        self.assertIn("l2", proposal.updated_design_vars)
        self.assertIn("cmrr", proposal.predicted_performances)


if __name__ == "__main__":
    unittest.main()
