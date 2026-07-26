from __future__ import annotations

import json
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.tagging.schemas import (
    FINAL_OUTPUT_SCHEMA,
    SchemaValidationError,
    validate_final_output,
    validate_step1_payload,
    validate_step2_payload,
)


class TestTaggingSchemas(unittest.TestCase):
    def test_validate_step1_payload_success(self) -> None:
        payload = {
            "functional_roles": [
                {
                    "name": "Main signal path",
                    "devices": ["M1", "M2"],
                    "description": "Differential input path",
                }
            ]
        }
        result = validate_step1_payload(payload)
        self.assertEqual(result["functional_roles"][0]["name"], "Main signal path")

    def test_validate_step1_payload_failure(self) -> None:
        payload = {
            "functional_roles": [
                {
                    "name": "Main signal path",
                    "devices": ["M1", "M2"],
                }
            ]
        }
        with self.assertRaises(SchemaValidationError):
            validate_step1_payload(payload)

    def test_validate_step2_payload_confidence_failure(self) -> None:
        payload = {
            "roles": [
                {
                    "name": "Main signal path",
                    "substructures": [
                        {
                            "type": "Differential Pair",
                            "devices": ["M1", "M2"],
                            "evidence": "M1 and M2 share source node",
                            "confidence": 1.5,
                            "variables": [],
                        }
                    ],
                }
            ]
        }
        with self.assertRaises(SchemaValidationError):
            validate_step2_payload(payload)

    def test_validate_step2_payload_variable_device_mismatch(self) -> None:
        payload = {
            "roles": [
                {
                    "name": "Main signal path",
                    "substructures": [
                        {
                            "type": "Differential Pair",
                            "devices": ["M1", "M2"],
                            "evidence": "M1 and M2 share source node",
                            "confidence": 0.9,
                            "variables": [
                                {"device": "M3", "design_variables": ["l2"]},
                            ],
                        }
                    ],
                }
            ]
        }
        with self.assertRaises(SchemaValidationError):
            validate_step2_payload(payload)

    def test_validate_step2_payload_normalizes_legacy_type(self) -> None:
        payload = {
            "roles": [
                {
                    "name": "Bias network",
                    "substructures": [
                        {
                            "type": "cascode current source",
                            "devices": ["M5"],
                            "evidence": "M5 is cascoded and supplies bias current",
                            "confidence": 0.82,
                            "variables": [
                                {"device": "M5", "design_variables": ["w5"]},
                            ],
                        }
                    ],
                }
            ]
        }

        result = validate_step2_payload(payload)
        sub = result["roles"][0]["substructures"][0]
        self.assertEqual(sub["type"], "Cascode current source")
        self.assertEqual(sub["base_type"], "current_source")
        self.assertEqual(sub["modifiers"], ["cascode"])

    def test_validate_final_output_success(self) -> None:
        payload = {
            "schema_version": "1.1.0",
            "tool": {
                "name": "two_stage_tagger",
                "provider": "openai",
                "model": "gpt-5.2",
                "generated_at_utc": "2026-02-21T00:00:00+00:00",
            },
            "input": {
                "netlist_path": "/tmp/test_netlist",
                "subckt_name": "test_subckt",
                "device_count": 2,
            },
            "stage1": {
                "functional_roles": [
                    {
                        "name": "Main signal path",
                        "devices": ["M1", "M2"],
                        "description": "Input path",
                    }
                ]
            },
            "stage2": {
                "roles": [
                    {
                        "name": "Main signal path",
                        "substructures": [
                            {
                                "type": "Differential Pair",
                                "devices": ["M1", "M2"],
                                "evidence": "M1 and M2 are input pair",
                                "confidence": 0.95,
                                "variables": [
                                    {
                                        "device": "M1",
                                        "design_variables": ["l2", "w2"],
                                    },
                                    {
                                        "device": "M2",
                                        "design_variables": ["l2", "w2"],
                                    },
                                ],
                            }
                        ],
                    }
                ]
            },
            "validation": {
                "stage1_unique_assignment_ok": True,
                "stage2_role_membership_ok": True,
                "all_devices_known": True,
                "duplicate_devices": [],
                "unknown_devices": [],
                "unassigned_devices": [],
            },
        }

        result = validate_final_output(payload)
        sub = result["stage2"]["roles"][0]["substructures"][0]
        self.assertEqual(sub["base_type"], "differential_pair")
        self.assertEqual(sub["modifiers"], [])

    def test_schema_file_matches_runtime_schema(self) -> None:
        schema_path = (
            AGENTIC_SIZING_ROOT
            / "src"
            / "agentic_sizing"
            / "tagging"
            / "tagging_output.schema.json"
        )
        file_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(
            file_schema["$schema"],
            "https://json-schema.org/draft/2020-12/schema",
        )
        self.assertIn("$id", file_schema)
        stripped_schema = {
            key: value
            for key, value in file_schema.items()
            if key not in {"$schema", "$id", "title"}
        }
        self.assertEqual(stripped_schema, FINAL_OUTPUT_SCHEMA)

    def test_example_file_validates_against_schema(self) -> None:
        example_path = (
            AGENTIC_SIZING_ROOT
            / "src"
            / "agentic_sizing"
            / "tagging"
            / "tagging_output.example.json"
        )
        payload = json.loads(example_path.read_text(encoding="utf-8"))
        validate_final_output(payload)


if __name__ == "__main__":
    unittest.main()
