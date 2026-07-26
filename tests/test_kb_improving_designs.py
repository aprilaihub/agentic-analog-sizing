from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from agentic_sizing.kb.improving_designs import generate_improving_designs


class TestImprovingDesignGeneration(unittest.TestCase):
    def test_constraint_first_trace_and_dimensions(self) -> None:
        settings = {
            "des_vars": {"w": [1, 10, 0]},
            "responses": {"assembler": ["power", "gain"]},
            "outputs": {
                "power": [10, "target", 1, "*value"],
                "gain": [5, "min", 2, "*value"],
            },
            "objective": {"name": "power", "minormax": "min"},
        }
        records = [
            {"iter": 1, "parameters": [1], "performance": [2, 3]},
            {"iter": 2, "parameters": [2], "performance": [4, 4]},
            {"iter": 3, "parameters": [3], "performance": [8, 5]},
            {"iter": 4, "parameters": [4], "performance": [7, 5]},
            {"iter": 5, "parameters": [5], "performance": [9, 5]},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings_path, records_path, output_path = (
                root / "x_settings.json",
                root / "records.json",
                root / "x_improving_designs.json",
            )
            settings_path.write_text(json.dumps(settings), encoding="utf-8")
            records_path.write_text(json.dumps(records), encoding="utf-8")
            result = generate_improving_designs(
                settings_path=str(settings_path),
                simulation_record_path=str(records_path),
                output_path=str(output_path),
            )

        self.assertEqual([item["iter"] for item in result], [1, 2, 3, 4])
        self.assertEqual([item["violations"] for item in result], [4.0, 2.0, 0.0, 0.0])
        self.assertEqual(result[-1]["validation"], 7.0)

    def test_even_limit_keeps_endpoints(self) -> None:
        settings = {
            "des_vars": {"w": [1, 10, 0]},
            "responses": {"assembler": ["score"]},
            "outputs": {"score": [0, "target", 1, "*value"]},
            "objective": {"name": "score", "minormax": "min"},
        }
        records = [{"iter": i, "parameters": [i], "performance": [10 - i]} for i in range(10)]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
            (root / "records.json").write_text(json.dumps(records), encoding="utf-8")
            result = generate_improving_designs(
                settings_path=str(root / "settings.json"),
                simulation_record_path=str(root / "records.json"),
                output_path=str(root / "out.json"),
                max_points=4,
            )
        self.assertEqual([item["iter"] for item in result], [0, 3, 6, 9])


if __name__ == "__main__":
    unittest.main()
