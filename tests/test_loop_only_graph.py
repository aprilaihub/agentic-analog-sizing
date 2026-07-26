from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.workflow.nodes.load_input import load_input


class TestLoopOnlyGraph(unittest.TestCase):
    def test_load_input_injects_default_roles(self) -> None:
        updates = load_input({})

        roles = updates.get("functional_roles", [])
        self.assertEqual(len(roles), 3)
        self.assertEqual([r.role_id for r in roles], ["input_stage", "load_stage", "compensation"])

        history = updates.get("history", [])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].node, "load_input")
        self.assertEqual(history[0].details.get("role_count"), 3)

    def test_build_state_graph_has_no_decompose_nodes(self) -> None:
        try:
            from agentic_sizing.workflow import build_state_graph
        except ImportError as exc:
            self.skipTest(f"langgraph unavailable: {exc}")

        graph = build_state_graph()
        node_names = set(getattr(graph, "nodes", {}).keys())
        self.assertNotIn("decompose_stage1", node_names)
        self.assertNotIn("decompose_stage2", node_names)

    def test_run_demo_history_has_no_decompose_events(self) -> None:
        try:
            from agentic_sizing.workflow.runner import run_demo
        except ImportError as exc:
            self.skipTest(f"langgraph unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmpdir:
            state = run_demo(
                netlist_path="/tmp/mock_netlist.sp",
                kb_root=tmpdir,
                max_iter=1,
                max_stagnation=1,
                mode="mock",
                simulation_record_path=f"{tmpdir}/simulation_record.json",
            )

        history_nodes = [record.node for record in state.get("history", [])]
        self.assertNotIn("decompose_stage1", history_nodes)
        self.assertNotIn("decompose_stage2", history_nodes)


if __name__ == "__main__":
    unittest.main()
