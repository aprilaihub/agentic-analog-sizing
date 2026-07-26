from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.llm.contract import StructuredGenerationResult
from agentic_sizing.tagging.pipeline import (
    TaggingPipelineError,
    _extract_device_names,
    run_two_stage_tagging,
)

NETLIST_TEXT = """// Library name: ada
// Cell name: 5T_ota
// View name: schematic
subckt ada_5T_ota_schematic vbn vdd vin vip vo
    M2 (vo vin net1 0) nch_lvt_mac l=l2 w=w2
    M1 (net5 vip net1 0) nch_lvt_mac l=l2 w=w2
    M0 (net2 net2 0 0) nch_lvt_mac l=l1 w=w1
    M0b (net1 net2 0 0) nch_lvt_mac l=l1 w=w1
    I1 (vbn net2) isource dc=Idc
    M3 (net5 net5 vdd vdd) pch_lvt_mac l=l3 w=w3
    M4 (vo net5 vdd vdd) pch_lvt_mac l=l3 w=w3
ends ada_5T_ota_schematic
"""


def _valid_stage1() -> dict:
    return {
        "functional_roles": [
            {
                "name": "Main signal path (input transconductor + active load)",
                "devices": ["M1", "M2", "M3", "M4"],
                "description": "Input differential pair with PMOS active load",
            },
            {
                "name": "Bias / reference generation (tail current bias)",
                "devices": ["M0", "M0b", "I1"],
                "description": "Tail bias generation and current injection",
            },
        ]
    }


def _valid_stage2() -> dict:
    return {
        "roles": [
            {
                "name": "Main signal path (input transconductor + active load)",
                "substructures": [
                    {
                        "type": "Differential Pair",
                        "devices": ["M1", "M2"],
                        "evidence": "M1/M2 gates are vip/vin and share source node net1",
                        "confidence": 0.96,
                        "variables": [
                            {"device": "M1", "design_variables": ["l2", "w2"]},
                            {"device": "M2", "design_variables": ["l2", "w2"]},
                        ],
                    },
                    {
                        "type": "Current Mirror",
                        "devices": ["M3", "M4"],
                        "evidence": "M3 diode-connected and mirrors to M4",
                        "confidence": 0.95,
                        "variables": [
                            {"device": "M3", "design_variables": ["l3", "w3"]},
                            {"device": "M4", "design_variables": ["l3", "w3"]},
                        ],
                    },
                ],
            },
            {
                "name": "Bias / reference generation (tail current bias)",
                "substructures": [
                    {
                        "type": "Current Mirror",
                        "devices": ["M0", "M0b"],
                        "evidence": "M0 diode-connected with M0b mirror output",
                        "confidence": 0.94,
                        "variables": [
                            {"device": "M0", "design_variables": ["l1", "w1"]},
                            {"device": "M0b", "design_variables": ["l1", "w1"]},
                        ],
                    },
                    {
                        "type": "Current Source",
                        "devices": ["I1"],
                        "evidence": "I1 injects bias current Idc",
                        "confidence": 0.9,
                        "variables": [
                            {"device": "I1", "design_variables": ["Idc"]},
                        ],
                    },
                ],
            },
        ]
    }


class TestTaggingPipeline(unittest.TestCase):
    def test_extract_device_names_preserves_escaped_bus_instance_names(self) -> None:
        netlist_text = """subckt Folded_cascode_two_stage vbn vdd vin vip von vop vref
    M28 (vbp1 vbp1 ncasc\\<0\\> vdd) pch l=L3 w=W3
    M27\\<6\\> (ncasc\\<6\\> vbp1 vdd vdd) pch l=L3 w=W3
    M27\\<0\\> (ncasc\\<0\\> vbp1 ncasc\\<1\\> vdd) pch l=L3 w=W3
    C0 (vop vfb_n) capacitor c=MCAP
ends Folded_cascode_two_stage
"""

        self.assertEqual(
            _extract_device_names(netlist_text),
            ["M28", "M27\\<6\\>", "M27\\<0\\>", "C0"],
        )

    def test_pipeline_retries_step2_and_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            netlist_path = Path(tmpdir) / "5t_ota"
            output_path = Path(tmpdir) / "5t_ota.json"
            netlist_path.write_text(NETLIST_TEXT, encoding="utf-8")

            bad_stage2 = {
                "roles": [
                    {
                        "name": "Main signal path (input transconductor + active load)",
                        "substructures": [
                            {
                                "type": "Differential Pair",
                                "devices": ["M1", "MX"],
                                "evidence": "invalid unknown device",
                                "confidence": 0.7,
                                "variables": [],
                            }
                        ],
                    }
                ]
            }

            with patch("agentic_sizing.tagging.pipeline.create_structured_client") as create_client:
                client = create_client.return_value
                client.generate_structured.side_effect = [
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_valid_stage1(),
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=bad_stage2,
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_valid_stage2(),
                        raw_text="{}",
                    ),
                ]

                result = run_two_stage_tagging(
                    input_path=str(netlist_path),
                    output_path=str(output_path),
                    max_retries=2,
                )

                self.assertTrue(result["validation"]["stage1_unique_assignment_ok"])
                self.assertTrue(result["validation"]["stage2_role_membership_ok"])
                self.assertTrue(result["validation"]["all_devices_known"])
                self.assertEqual(client.generate_structured.call_count, 3)
                first_request = client.generate_structured.call_args_list[0].args[0]
                second_request = client.generate_structured.call_args_list[1].args[0]
                self.assertEqual(first_request.reasoning_effort, "low")
                self.assertEqual(second_request.reasoning_effort, "low")

            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], "1.1.0")
            first_sub = saved["stage2"]["roles"][0]["substructures"][0]
            self.assertEqual(first_sub["base_type"], "differential_pair")
            self.assertEqual(first_sub["modifiers"], [])
            self.assertEqual(saved["input"]["device_count"], 7)

    def test_pipeline_fails_on_stage2_membership_without_retry_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            netlist_path = Path(tmpdir) / "5t_ota"
            netlist_path.write_text(NETLIST_TEXT, encoding="utf-8")

            bad_stage2 = {
                "roles": [
                    {
                        "name": "Bias / reference generation (tail current bias)",
                        "substructures": [
                            {
                                "type": "Current Mirror",
                                "devices": ["M2"],
                                "evidence": "M2 is not in bias role",
                                "confidence": 0.7,
                                "variables": [],
                            }
                        ],
                    }
                ]
            }

            with patch("agentic_sizing.tagging.pipeline.create_structured_client") as create_client:
                client = create_client.return_value
                client.generate_structured.side_effect = [
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_valid_stage1(),
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=bad_stage2,
                        raw_text="{}",
                    ),
                ]

                with self.assertRaises(TaggingPipelineError):
                    run_two_stage_tagging(input_path=str(netlist_path), max_retries=0)
                first_request = client.generate_structured.call_args_list[0].args[0]
                second_request = client.generate_structured.call_args_list[1].args[0]
            self.assertEqual(first_request.reasoning_effort, "low")
            self.assertEqual(second_request.reasoning_effort, "low")

    def test_pipeline_surfaces_connection_error_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            netlist_path = Path(tmpdir) / "5t_ota"
            netlist_path.write_text(NETLIST_TEXT, encoding="utf-8")

            with patch("agentic_sizing.tagging.pipeline.create_structured_client") as create_client:
                client = create_client.return_value
                client.generate_structured.side_effect = ConnectionError("network down")

                with self.assertRaises(TaggingPipelineError) as ctx:
                    run_two_stage_tagging(input_path=str(netlist_path), max_retries=0)

            message = str(ctx.exception)
            self.assertIn("step1 failed after 1 attempts", message)
            self.assertIn("ConnectionError: network down", message)
            self.assertIn("OpenAI Responses API", message)

    def test_pipeline_accepts_stage1_devices_with_escaped_bus_names(self) -> None:
        netlist_text = """subckt Folded_cascode_two_stage vbn vdd vin vip von vop vref
    M28 (vbp1 vbp1 ncasc\\<0\\> vdd) pch l=L3 w=W3
    M27\\<1\\> (ncasc\\<1\\> vbp1 vdd vdd) pch l=L3 w=W3
    M27\\<0\\> (ncasc\\<0\\> vbp1 ncasc\\<1\\> vdd) pch l=L3 w=W3
ends Folded_cascode_two_stage
"""

        stage1 = {
            "functional_roles": [
                {
                    "name": "Bias network",
                    "devices": ["M28", "M27\\<1\\>", "M27\\<0\\>"],
                    "description": "PMOS bias stack",
                }
            ]
        }
        stage2 = {
            "roles": [
                {
                    "name": "Bias network",
                    "substructures": [
                        {
                            "type": "Current source",
                            "devices": ["M28", "M27\\<1\\>", "M27\\<0\\>"],
                            "evidence": "Three PMOS devices form the bias branch.",
                            "confidence": 0.88,
                            "variables": [
                                {"device": "M28", "design_variables": ["L3", "W3"]},
                                {"device": "M27\\<1\\>", "design_variables": ["L3", "W3"]},
                                {"device": "M27\\<0\\>", "design_variables": ["L3", "W3"]},
                            ],
                        }
                    ],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            netlist_path = Path(tmpdir) / "folded_cascode_2stage"
            output_path = Path(tmpdir) / "folded_cascode_2stage.json"
            netlist_path.write_text(netlist_text, encoding="utf-8")

            with patch("agentic_sizing.tagging.pipeline.create_structured_client") as create_client:
                client = create_client.return_value
                client.generate_structured.side_effect = [
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=stage1,
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=stage2,
                        raw_text="{}",
                    ),
                ]

                result = run_two_stage_tagging(
                    input_path=str(netlist_path),
                    output_path=str(output_path),
                    max_retries=0,
                )

        self.assertTrue(result["validation"]["all_devices_known"])
        self.assertEqual(result["validation"]["unknown_devices"], [])
        self.assertEqual(result["input"]["device_count"], 3)


if __name__ == "__main__":
    unittest.main()
