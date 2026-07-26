from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from agentic_sizing.kb.critical_heuristics import (
    retrieve_critical_heuristics,
    validate_critical_heuristics_payload,
    write_case_and_rebuild_global_heuristics,
)


def _payload(case: str) -> dict:
    return {
        "heuristics": [
            {
                "case_name": case,
                "condition": {"target_metrics": ["load_regulation"]},
                "heuristic": "Strengthen loop authority before fine compensation tuning while preserving output headroom.",
                "priority": "high",
                "scope": "both",
            },
            {
                "case_name": case,
                "condition": {"target_metrics": ["load_regulation"]},
                "heuristic": "Stabilize the feedback operating point before evaluating load-dependent regulation changes.",
                "priority": "high",
                "scope": "worker",
            },
            {
                "case_name": case,
                "condition": {"target_metrics": ["psrr"]},
                "heuristic": "Recover supply rejection before aggressive objective optimization can reopen feasibility.",
                "priority": "medium",
                "scope": "planner",
            },
        ]
    }


class TestCriticalHeuristicExtraction(unittest.TestCase):
    def test_validate_write_global_and_cross_case_retrieve(self) -> None:
        items = validate_critical_heuristics_payload(
            _payload("ldo2"),
            case_name="ldo2",
            allowed_metrics={"load_regulation", "psrr"},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = write_case_and_rebuild_global_heuristics(
                case_name="ldo2", heuristics=items, base_dir=tmpdir
            )
            case_payload = json.loads(Path(paths["case"]).read_text(encoding="utf-8"))
            global_payload = json.loads(Path(paths["global"]).read_text(encoding="utf-8"))
            transferred = retrieve_critical_heuristics(
                case_name="ldo_full",
                target_metric="load_regulation",
                scope="worker",
                base_dir=tmpdir,
            )

        self.assertIsInstance(case_payload, list)
        self.assertEqual(case_payload, global_payload)
        self.assertEqual(len(transferred), 2)

    def test_rejects_unknown_metric(self) -> None:
        with self.assertRaises(ValueError):
            validate_critical_heuristics_payload(
                _payload("ldo2"), case_name="ldo2", allowed_metrics={"power"}
            )


if __name__ == "__main__":
    unittest.main()
