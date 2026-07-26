from __future__ import annotations

import json
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
SIM_ROOT = AGENTIC_SIZING_ROOT / "src" / "agentic_sizing" / "simulator"
EXAMPLE_PATH = AGENTIC_SIZING_ROOT / "examples" / "data" / "5t_ota_improving_designs.json"
SETTINGS_PATH = AGENTIC_SIZING_ROOT / "src" / "agentic_sizing" / "specs" / "5t_ota_settings.json"


class TestSimulatorImprovingDesignsContract(unittest.TestCase):
    def test_schema_and_example_exist(self) -> None:
        schema_path = SIM_ROOT / "improving_designs.schema.json"
        self.assertTrue(schema_path.exists())
        self.assertTrue(EXAMPLE_PATH.exists())

    def test_schema_shape(self) -> None:
        schema = json.loads(
            (SIM_ROOT / "improving_designs.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema.get("type"), "array")

        item_schema = schema.get("items", {})
        self.assertEqual(item_schema.get("type"), "object")
        self.assertFalse(item_schema.get("additionalProperties", True))

        required = set(item_schema.get("required", []))
        self.assertEqual(
            required,
            {"iter", "parameters", "performance", "validation", "objective", "violations"},
        )

    def test_example_record_structure_and_types(self) -> None:
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.assertIsInstance(example, list)
        self.assertGreater(len(example), 0)

        expected_keys = {
            "iter",
            "parameters",
            "performance",
            "validation",
            "objective",
            "violations",
        }
        for idx, item in enumerate(example):
            self.assertIsInstance(item, dict, f"item[{idx}] must be object")
            self.assertEqual(set(item.keys()), expected_keys)
            self.assertIsInstance(item["iter"], int)
            self.assertGreaterEqual(item["iter"], 0)
            self.assertIsInstance(item["parameters"], list)
            self.assertGreater(len(item["parameters"]), 0)
            self.assertTrue(all(isinstance(v, (int, float)) for v in item["parameters"]))
            self.assertIsInstance(item["performance"], list)
            self.assertGreater(len(item["performance"]), 0)
            self.assertTrue(all(isinstance(v, (int, float)) for v in item["performance"]))
            self.assertIsInstance(item["validation"], (int, float))
            self.assertIsInstance(item["objective"], (int, float))
            self.assertIsInstance(item["violations"], (int, float))
            self.assertGreaterEqual(item["violations"], 0.0)

    def test_semantic_consistency_for_5t_ota_example(self) -> None:
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

        expected_param_dim = len(settings["des_vars"])
        expected_perf_dim = len(settings["responses"]["assembler"])
        self.assertEqual(expected_param_dim, 7)
        self.assertEqual(expected_perf_dim, 10)

        iters = [entry["iter"] for entry in example]
        self.assertEqual(len(iters), len(set(iters)))
        for idx in range(len(iters) - 1):
            self.assertLess(iters[idx], iters[idx + 1], "iter should be strictly increasing")

        for idx, entry in enumerate(example):
            self.assertEqual(
                len(entry["parameters"]),
                expected_param_dim,
                f"item[{idx}] parameters dimension mismatch",
            )
            self.assertEqual(
                len(entry["performance"]),
                expected_perf_dim,
                f"item[{idx}] performance dimension mismatch",
            )
            self.assertAlmostEqual(
                float(entry["objective"]),
                float(entry["performance"][0]),
                places=12,
                msg=f"item[{idx}] objective should equal performance[0]",
            )
            self.assertAlmostEqual(
                float(entry["validation"]),
                float(entry["objective"]) + float(entry["violations"]),
                places=12,
                msg=f"item[{idx}] validation should equal objective + violations",
            )


if __name__ == "__main__":
    unittest.main()
