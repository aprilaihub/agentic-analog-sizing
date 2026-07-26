from __future__ import annotations

import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.kb.merge import merge_fact_lists


def _perf_fact(
    subject: str, obj: str, direction: str, evidence_count: int, confidence: float
) -> dict:
    return {
        "type": "perf_perf_tradeoff",
        "subject": subject,
        "relation": "trades_off_with",
        "object": obj,
        "direction": direction,
        "confidence": confidence,
        "evidence_count": evidence_count,
        "evidence_iters": [1],
        "topology": "5t_ota",
    }


def _role_fact(role: str, metric: str, influence: str) -> dict:
    return {
        "type": "role_perf",
        "functional_role": role,
        "metric": metric,
        "influence": influence,
        "confidence": 0.8,
        "evidence_count": 2,
        "evidence_iters": [1, 2],
        "topology": "5t_ota",
    }


class TestKBMergePolicy(unittest.TestCase):
    def test_new_fact_is_added(self) -> None:
        existing = [
            _perf_fact("power", "slew_rate_rise", "positive", evidence_count=2, confidence=0.7)
        ]
        new = [_perf_fact("power", "pm", "negative", evidence_count=1, confidence=0.6)]

        merged = merge_fact_lists(
            existing_facts=existing,
            new_facts=new,
            omit_conflicts=True,
            same_fact_policy="keep_duplicates",
        )

        self.assertEqual(len(merged), 2)

    def test_same_fact_keep_duplicates_and_merge_strengthen(self) -> None:
        existing = [
            _perf_fact("power", "slew_rate_rise", "positive", evidence_count=2, confidence=0.5)
        ]
        new = [_perf_fact("power", "slew_rate_rise", "positive", evidence_count=3, confidence=0.9)]

        merged_keep = merge_fact_lists(
            existing_facts=existing,
            new_facts=new,
            omit_conflicts=True,
            same_fact_policy="keep_duplicates",
        )
        self.assertEqual(len(merged_keep), 2)

        merged_strengthen = merge_fact_lists(
            existing_facts=existing,
            new_facts=new,
            omit_conflicts=True,
            same_fact_policy="merge_strengthen",
        )
        self.assertEqual(len(merged_strengthen), 1)
        self.assertEqual(merged_strengthen[0]["evidence_count"], 5)
        self.assertAlmostEqual(merged_strengthen[0]["confidence"], 0.74, places=2)

    def test_opposite_directions_collapse_to_one_unspecified_fact(self) -> None:
        existing = [
            _perf_fact("power", "slew_rate_rise", "positive", evidence_count=2, confidence=0.8)
        ]
        new = [_perf_fact("power", "slew_rate_rise", "negative", evidence_count=1, confidence=0.6)]

        merged_omit = merge_fact_lists(
            existing_facts=existing,
            new_facts=new,
            omit_conflicts=True,
            same_fact_policy="merge_strengthen",
        )
        self.assertEqual(len(merged_omit), 1)
        self.assertEqual(merged_omit[0]["direction"], "unspecified")
        self.assertEqual(merged_omit[0]["evidence_count"], 3)

        merged_keep_conflicts = merge_fact_lists(
            existing_facts=existing,
            new_facts=new,
            omit_conflicts=False,
            same_fact_policy="keep_duplicates",
        )
        self.assertEqual(len(merged_keep_conflicts), 2)
        self.assertTrue(all(fact["direction"] == "unspecified" for fact in merged_keep_conflicts))

    def test_opposite_influence_removes_role_family(self) -> None:
        existing = [_role_fact("Bias network", "power", "dominant")]
        new = [_role_fact("Bias network", "power", "weak")]

        merged = merge_fact_lists(
            existing_facts=existing,
            new_facts=new,
            omit_conflicts=True,
            same_fact_policy="keep_duplicates",
        )

        self.assertEqual(merged, [])

    def test_symmetric_perf_tradeoff_pairs_are_canonicalized(self) -> None:
        existing = [_perf_fact("adm", "lg_ugb", "negative", evidence_count=2, confidence=0.7)]
        new = [_perf_fact("lg_ugb", "adm", "negative", evidence_count=3, confidence=0.9)]

        merged = merge_fact_lists(
            existing_facts=existing,
            new_facts=new,
            omit_conflicts=True,
            same_fact_policy="merge_strengthen",
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["subject"], "adm")
        self.assertEqual(merged[0]["object"], "lg_ugb")
        self.assertEqual(merged[0]["evidence_count"], 5)

    def test_directionless_tradeoffs_do_not_infer_transitive_relation(self) -> None:
        existing = [
            _perf_fact("power", "slew_rate_rise", "positive", evidence_count=4, confidence=0.9),
            _perf_fact("lg_ugb", "slew_rate_rise", "positive", evidence_count=3, confidence=0.8),
        ]

        merged = merge_fact_lists(
            existing_facts=existing,
            new_facts=[],
            omit_conflicts=True,
            same_fact_policy="merge_strengthen",
        )

        inferred = [
            fact
            for fact in merged
            if fact.get("type") == "perf_perf_tradeoff"
            and fact.get("subject") == "lg_ugb"
            and fact.get("object") == "power"
            and fact.get("direction") == "unspecified"
        ]
        self.assertEqual(inferred, [])

    def test_inference_does_not_override_existing_direct_pair(self) -> None:
        existing = [
            _perf_fact("power", "slew_rate_rise", "positive", evidence_count=4, confidence=0.9),
            _perf_fact("lg_ugb", "slew_rate_rise", "positive", evidence_count=3, confidence=0.8),
            _perf_fact("lg_ugb", "power", "negative", evidence_count=5, confidence=0.7),
        ]

        merged = merge_fact_lists(
            existing_facts=existing,
            new_facts=[],
            omit_conflicts=True,
            same_fact_policy="merge_strengthen",
        )

        direct_pairs = [
            fact
            for fact in merged
            if fact.get("type") == "perf_perf_tradeoff"
            and fact.get("subject") == "lg_ugb"
            and fact.get("object") == "power"
        ]
        self.assertEqual(len(direct_pairs), 1)
        self.assertEqual(direct_pairs[0]["direction"], "unspecified")


if __name__ == "__main__":
    unittest.main()
