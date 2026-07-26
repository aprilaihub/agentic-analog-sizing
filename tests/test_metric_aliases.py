from __future__ import annotations

import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.core.metric_aliases import canonical_metric_name
from agentic_sizing.iteration.context import filter_substruct_param_perf_facts
from agentic_sizing.kb.interpreter import (
    summarize_perf_tradeoff_facts,
    summarize_substruct_param_perf_facts,
)


class TestMetricAliases(unittest.TestCase):
    def test_canonical_metric_name_maps_rise_time(self) -> None:
        self.assertEqual(canonical_metric_name("rise_time"), "slew_rate_rise")

    def test_substruct_param_filter_matches_metric_alias(self) -> None:
        facts = {
            "facts": [
                {
                    "substructure": "Differential pair",
                    "parameter": "w",
                    "metric": "slew_rate_rise",
                    "confidence": 0.8,
                }
            ]
        }
        result = filter_substruct_param_perf_facts(
            facts,
            ["Differential pair"],
            allowed_metrics=["rise_time"],
            role_variables=["w2"],
        )
        self.assertEqual(len(result["facts"]), 1)

    def test_substruct_param_filter_matches_generic_rd_to_rd2(self) -> None:
        facts = {
            "facts": [
                {
                    "substructure": "Resistor divider",
                    "parameter": "RD",
                    "metric": "load_regulation",
                    "confidence": 0.9,
                }
            ]
        }
        result = filter_substruct_param_perf_facts(
            facts,
            ["Resistor divider"],
            allowed_metrics=["load_regulation"],
            role_variables=["RD2"],
        )
        self.assertEqual(len(result["facts"]), 1)

    def test_substruct_param_filter_does_not_require_substructure_match(self) -> None:
        facts = {
            "facts": [
                {
                    "substructure": "Folded cascode",
                    "parameter": "RD",
                    "metric": "load_regulation",
                    "confidence": 0.9,
                }
            ]
        }
        result = filter_substruct_param_perf_facts(
            facts,
            ["Resistor divider"],
            allowed_metrics=["load_regulation"],
            role_variables=["RD2"],
        )
        self.assertEqual(len(result["facts"]), 1)

    def test_substruct_param_filter_does_not_require_parameter_match(self) -> None:
        facts = {
            "facts": [
                {
                    "substructure": "Resistor divider",
                    "parameter": "R",
                    "metric": "load_regulation",
                    "confidence": 0.9,
                }
            ]
        }
        result = filter_substruct_param_perf_facts(
            facts,
            ["Resistor divider"],
            allowed_metrics=["load_regulation"],
            role_variables=["RD2"],
        )
        self.assertEqual(len(result["facts"]), 1)

    def test_substruct_param_filter_rejects_different_metric(self) -> None:
        facts = {
            "facts": [
                {
                    "substructure": "Common-source stage",
                    "parameter": "L",
                    "metric": "power",
                    "confidence": 0.9,
                }
            ]
        }
        result = filter_substruct_param_perf_facts(
            facts,
            ["Resistor divider"],
            allowed_metrics=["psrr"],
            role_variables=["RD2"],
        )
        self.assertEqual(result["facts"], [])

    def test_kb_summary_matches_metric_alias(self) -> None:
        facts = {
            "facts": [
                {
                    "substructure": "Differential pair",
                    "parameter": "w",
                    "metric": "slew_rate_rise",
                    "confidence": 0.8,
                    "evidence_count": 3,
                }
            ]
        }
        summary = summarize_substruct_param_perf_facts(facts, target_metrics=["rise_time"])
        self.assertEqual(
            summary,
            [
                "Differential pair.w: is a critical parameter for slew_rate_rise; "
                "direction intentionally unspecified (conf 0.80)."
            ],
        )

    def test_agent_facing_kb_summary_hides_tradeoff_direction(self) -> None:
        facts = {
            "facts": [
                {
                    "subject": "power",
                    "relation": "trades_off_with",
                    "object": "psrr",
                    "direction": "negative",
                    "confidence": 0.9,
                    "evidence_count": 4,
                }
            ]
        }
        summary = summarize_perf_tradeoff_facts(facts)
        self.assertEqual(
            summary,
            [
                "power vs psrr: performance metrics are coupled; direction intentionally "
                "unspecified (conf 0.90, n=4)."
            ],
        )
        self.assertNotIn("negative", summary[0])


if __name__ == "__main__":
    unittest.main()
