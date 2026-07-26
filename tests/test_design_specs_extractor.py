from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.specs.extract_design_specs import (
    RULE_MAPPING,
    extract_design_specs_file,
    extract_design_specs_from_settings,
    load_specs_extractor_prompt,
)


class TestDesignSpecsExtractor(unittest.TestCase):
    def setUp(self) -> None:
        self.input_settings_path = AGENTIC_SIZING_ROOT / "input" / "kb" / "5t_ota_settings.json"
        self.settings = json.loads(self.input_settings_path.read_text(encoding="utf-8"))

    def test_design_specs_schema_has_expected_required_fields(self) -> None:
        schema_path = (
            AGENTIC_SIZING_ROOT / "src" / "agentic_sizing" / "specs" / "design_specs.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        required = set(schema.get("required", []))
        self.assertEqual(
            required,
            {
                "schema_version",
                "topology",
                "objective",
                "design_variables",
                "performance_specs",
            },
        )

    def test_specs_extractor_prompt_exists_and_is_non_empty(self) -> None:
        prompt = load_specs_extractor_prompt()
        self.assertIn("design_specs", prompt)
        self.assertGreater(len(prompt.strip()), 50)

    def test_extract_from_5t_ota_settings_has_expected_structure_and_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "5t_ota_design_specs.json"
            payload = extract_design_specs_file(
                input_settings_path=str(self.input_settings_path),
                output_path=str(output_path),
            )

            self.assertTrue(output_path.exists())
            file_payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, file_payload)

        self.assertEqual(payload["schema_version"], "1.0.0")
        self.assertEqual(payload["topology"], "5t_ota")
        self.assertEqual(payload["objective"]["metric"], self.settings["objective"]["name"])
        self.assertEqual(payload["objective"]["sense"], self.settings["objective"]["minormax"])

        des_var_items = list(self.settings["des_vars"].items())
        extracted_vars = payload["design_variables"]
        self.assertEqual(len(extracted_vars), len(des_var_items))
        for idx, (var_name, raw_range) in enumerate(des_var_items):
            row = extracted_vars[idx]
            self.assertEqual(row["name"], var_name)
            self.assertEqual(row["min"], float(raw_range[0]))
            self.assertEqual(row["max"], float(raw_range[1]))
            expected_is_integer = bool(raw_range[2]) if len(raw_range) == 3 else False
            self.assertEqual(row["is_integer"], expected_is_integer)

        metrics = self.settings["responses"]["assembler"]
        extracted_specs = payload["performance_specs"]
        self.assertEqual(len(extracted_specs), len(metrics))

        objective_matches = 0
        for idx, metric in enumerate(metrics):
            spec = extracted_specs[idx]
            output_entry = self.settings["outputs"][metric]
            method = output_entry[1]

            self.assertEqual(spec["name"], metric)
            self.assertEqual(spec["index"], idx)
            self.assertEqual(spec["method"], method)
            self.assertEqual(spec["rule"], RULE_MAPPING[method])
            self.assertEqual(spec["threshold"], float(output_entry[0]))
            self.assertEqual(spec["weight"], float(output_entry[2]))
            self.assertEqual(spec["calc_expr"], output_entry[3])

            if spec["is_objective"]:
                objective_matches += 1
                self.assertEqual(metric, self.settings["objective"]["name"])

        self.assertEqual(objective_matches, 1)

    def test_extract_fails_when_required_field_missing(self) -> None:
        broken = dict(self.settings)
        broken.pop("outputs", None)
        with self.assertRaisesRegex(ValueError, "settings.outputs"):
            extract_design_specs_from_settings(broken, "5t_ota")

    def test_extract_fails_when_objective_not_in_responses(self) -> None:
        broken = dict(self.settings)
        broken["objective"] = dict(self.settings["objective"])
        broken["objective"]["name"] = "not_a_metric"
        with self.assertRaisesRegex(ValueError, "not found in settings.responses.assembler"):
            extract_design_specs_from_settings(broken, "5t_ota")

    def test_extract_fails_when_method_invalid(self) -> None:
        broken = dict(self.settings)
        broken["outputs"] = dict(self.settings["outputs"])
        broken["outputs"]["cmrr"] = list(self.settings["outputs"]["cmrr"])
        broken["outputs"]["cmrr"][1] = "unsupported"

        with self.assertRaisesRegex(ValueError, "must be one of"):
            extract_design_specs_from_settings(broken, "5t_ota")


if __name__ == "__main__":
    unittest.main()
