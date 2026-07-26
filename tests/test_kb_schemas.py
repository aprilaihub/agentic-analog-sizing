from __future__ import annotations

import json
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.kb.schemas import (
    load_kb_perf_tradeoff_schema,
    load_kb_role_perf_schema,
    load_kb_substruct_param_perf_schema,
    validate_perf_tradeoff_payload,
    validate_role_perf_payload,
    validate_substruct_param_perf_payload,
)


class TestKBSchemas(unittest.TestCase):
    def test_schema_files_load(self) -> None:
        self.assertEqual(load_kb_perf_tradeoff_schema().get("type"), "object")
        self.assertEqual(load_kb_substruct_param_perf_schema().get("type"), "object")
        self.assertEqual(load_kb_role_perf_schema().get("type"), "object")

    def test_example_files_validate(self) -> None:
        kb_dir = AGENTIC_SIZING_ROOT / "src" / "agentic_sizing" / "kb"
        perf_example = json.loads(
            (kb_dir / "kb_perf_tradeoff.example.json").read_text(encoding="utf-8")
        )
        substruct_example = json.loads(
            (kb_dir / "kb_substruct_param_perf.example.json").read_text(encoding="utf-8")
        )
        role_example = json.loads(
            (kb_dir / "kb_role_perf.example.json").read_text(encoding="utf-8")
        )

        metrics = {
            "power",
            "cmrr",
            "adm",
            "output_swing",
            "pm",
            "rms_noise_out",
            "lg_ugb",
            "psrr",
            "slew_rate_rise",
            "slew_rate_fall",
        }
        params = {"l", "w", "Idc"}
        substructures = {
            "Differential Pair",
            "Current Mirror",
            "Current Mirror (active load)",
            "Current Source",
        }
        roles = {
            "Main signal path (input transconductor + active load)",
            "Bias / reference generation (tail current bias)",
        }

        perf = validate_perf_tradeoff_payload(
            perf_example, allowed_metrics=metrics, topology="5t_ota"
        )
        substruct = validate_substruct_param_perf_payload(
            substruct_example,
            allowed_substructures=substructures,
            allowed_parameters=params,
            allowed_metrics=metrics,
            topology="5t_ota",
        )
        role = validate_role_perf_payload(
            role_example,
            allowed_roles=roles,
            allowed_metrics=metrics,
            topology="5t_ota",
        )

        self.assertGreaterEqual(len(perf["facts"]), 3)
        self.assertGreaterEqual(len(substruct["facts"]), 8)
        self.assertGreaterEqual(len(role["facts"]), 4)
        self.assertTrue(all(fact["parameter"] in params for fact in substruct["facts"]))


if __name__ == "__main__":
    unittest.main()
