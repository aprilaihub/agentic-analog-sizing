from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.kb.critical_heuristics import retrieve_critical_heuristics


class TestCriticalHeuristics(unittest.TestCase):
    def test_retrieve_by_case_name_and_target_metric(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "telescopic_critical_heuristics.json").write_text(
                json.dumps(
                    [
                        {
                            "case_name": "telescopic",
                            "condition": {"target_metrics": ["slew_rate_rise", "slew_rate_fall"]},
                            "heuristic": "Increase Idc for slew rate.",
                            "priority": "high",
                            "scope": "worker",
                        },
                        {
                            "case_name": "telescopic",
                            "condition": {"target_metrics": ["rms_noise_out"]},
                            "heuristic": "Increase input pair area for noise.",
                            "priority": "critical",
                            "scope": "planner",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = retrieve_critical_heuristics(
                case_name="telescopic",
                target_metric="slew_rate_rise",
                scope="worker",
                base_dir=base,
            )

        self.assertEqual(result, ["Increase Idc for slew rate."])

    def test_retrieve_matches_any_of_multiple_target_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "telescopic_critical_heuristics.json").write_text(
                json.dumps(
                    [
                        {
                            "case_name": "telescopic",
                            "condition": {"target_metrics": ["slew_rate_rise", "slew_rate_fall"]},
                            "heuristic": "Increase Idc for slew rate.",
                            "priority": "high",
                            "scope": "worker",
                        },
                        {
                            "case_name": "telescopic",
                            "condition": {"target_metrics": ["rms_noise_out"]},
                            "heuristic": "Resize input pair/load for noise.",
                            "priority": "high",
                            "scope": "planner",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = retrieve_critical_heuristics(
                case_name="telescopic",
                target_metrics=["pm", "rms_noise_out"],
                scope="planner",
                base_dir=base,
            )

        self.assertEqual(result, ["Resize input pair/load for noise."])

    def test_scope_filters_out_other_agent_heuristics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "telescopic_critical_heuristics.json").write_text(
                json.dumps(
                    [
                        {
                            "case_name": "telescopic",
                            "condition": {"target_metrics": ["slew_rate_rise"]},
                            "heuristic": "Planner heuristic",
                            "priority": "high",
                            "scope": "planner",
                        },
                        {
                            "case_name": "telescopic",
                            "condition": {"target_metrics": ["slew_rate_rise"]},
                            "heuristic": "Worker heuristic",
                            "priority": "high",
                            "scope": "worker",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = retrieve_critical_heuristics(
                case_name="telescopic",
                target_metric="slew_rate_rise",
                scope="planner",
                base_dir=base,
            )

        self.assertEqual(result, ["Planner heuristic"])

    def test_missing_case_file_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = retrieve_critical_heuristics(
                case_name="missing_case",
                target_metric="slew_rate_rise",
                base_dir=td,
            )
        self.assertEqual(result, [])

    def test_metric_alias_matches_synonym(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "telescopic_critical_heuristics.json").write_text(
                json.dumps(
                    [
                        {
                            "case_name": "telescopic",
                            "condition": {"target_metrics": ["slew_rate_rise"]},
                            "heuristic": "Increase Idc for slew rate.",
                            "priority": "high",
                            "scope": "worker",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            result = retrieve_critical_heuristics(
                case_name="telescopic",
                target_metric="rise_time",
                scope="worker",
                base_dir=base,
            )

        self.assertEqual(result, ["Increase Idc for slew rate."])


if __name__ == "__main__":
    unittest.main()
