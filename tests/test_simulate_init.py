from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
simulate_init_module = importlib.import_module("agentic_sizing.workflow.nodes.simulate_init")
simulate_init = simulate_init_module.simulate_init


class TestSimulateInit(unittest.TestCase):
    def test_mock_mode_prepares_runtime_seed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            record_path = Path(td) / "simulation_record.json"
            state = {
                "initialize_mode": "mock",
                "simulation_backend": "mock",
                "netlist_path": "input/tagging/5t_ota",
                "simulation_record_path": str(record_path),
                "current_design_vars": {
                    "gm1": 1.1,
                    "gm2": 1.0,
                    "rout": 8.0,
                    "cc": 1.0,
                    "ibias": 1.0,
                },
                "iteration": 0,
                "history": [],
            }
            seed_result = {
                "seed_name": "global",
                "copied_files": {
                    "perf_tradeoff": "/tmp/a.json",
                    "substruct_param_perf": "/tmp/b.json",
                    "role_perf": "/tmp/c.json",
                },
            }

            with patch.object(
                simulate_init_module,
                "prepare_runtime_kb_from_seed",
                return_value=seed_result,
            ) as mock_prepare:
                updates = simulate_init(state)

            mock_prepare.assert_called_once_with(case_name="5t_ota")

            self.assertEqual(updates["case_name"], "5t_ota")
            self.assertTrue(record_path.exists())

            records = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["iter"], 1)

            history = updates["history"]
            self.assertGreaterEqual(len(history), 1)
            self.assertEqual(history[-1].node, "simulate_init")
            self.assertEqual(history[-1].details["kb_seed"]["seed_name"], "global")


if __name__ == "__main__":
    unittest.main()
