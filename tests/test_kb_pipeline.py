from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.kb.pipeline import KBFactExtractionError, run_kb_fact_extraction
from agentic_sizing.llm.contract import StructuredGenerationResult


def _settings_payload() -> dict:
    return {
        "responses": {
            "assembler": [
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
            ]
        },
        "des_vars": {
            "l1": [6e-8, 5e-6, 0],
            "l2": [6e-8, 5e-6, 0],
            "l3": [6e-8, 5e-6, 0],
            "w1": [1.2e-7, 1e-4, 0],
            "w2": [1.2e-7, 1e-4, 0],
            "w3": [1.2e-7, 1e-4, 0],
            "Idc": [1e-6, 1e-5, 0],
        },
    }


def _tagging_payload() -> dict:
    return {
        "stage1": {
            "functional_roles": [
                {
                    "name": "Main signal path (input transconductor + active load)",
                    "devices": ["M1", "M2", "M3", "M4"],
                    "description": "signal role",
                },
                {
                    "name": "Bias / reference generation (tail current bias)",
                    "devices": ["M0", "M0b", "I1"],
                    "description": "bias role",
                },
            ]
        },
        "stage2": {
            "roles": [
                {
                    "name": "Main signal path (input transconductor + active load)",
                    "substructures": [
                        {"type": "Differential Pair", "devices": ["M1", "M2"]},
                        {"type": "Current Mirror (active load)", "devices": ["M3", "M4"]},
                    ],
                },
                {
                    "name": "Bias / reference generation (tail current bias)",
                    "substructures": [
                        {"type": "Current Mirror", "devices": ["M0", "M0b"]},
                        {"type": "Current Source", "devices": ["I1"]},
                    ],
                },
            ]
        },
    }


def _perf_tradeoff_payload() -> dict:
    return {
        "facts": [
            {
                "type": "perf_perf_tradeoff",
                "subject": "power",
                "relation": "trades_off_with",
                "object": "slew_rate_rise",
                "direction": "direct",
                "confidence": 0.8,
                "evidence_count": 8,
                "evidence_iters": [1, 29, 40],
                "topology": "5t_ota",
            },
            {
                "type": "perf_perf_tradeoff",
                "subject": "adm",
                "relation": "trades_off_with",
                "object": "rms_noise_out",
                "direction": "inverse",
                "confidence": 0.7,
                "evidence_count": 7,
                "evidence_iters": [29, 40, 61],
                "topology": "5t_ota",
            },
            {
                "type": "perf_perf_tradeoff",
                "subject": "rms_noise_out",
                "relation": "trades_off_with",
                "object": "psrr",
                "direction": "negative",
                "confidence": 0.6,
                "evidence_count": 6,
                "evidence_iters": [61, 88, 90],
                "topology": "5t_ota",
            },
        ]
    }


def _substruct_param_perf_payload() -> dict:
    return {
        "facts": [
            {
                "type": "substruct_param_perf",
                "substructure": "Current Mirror",
                "parameter": "l1",
                "metric": "rms_noise_out",
                "direction": "increase_degrades",
                "confidence": 0.8,
                "evidence_count": 9,
                "evidence_iters": [1, 29, 61],
                "topology": "5t_ota",
            },
            {
                "type": "substruct_param_perf",
                "substructure": "Current Mirror",
                "parameter": "w1",
                "metric": "cmrr",
                "direction": "negative",
                "confidence": 0.7,
                "evidence_count": 8,
                "evidence_iters": [1, 29, 61],
                "topology": "5t_ota",
            },
            {
                "type": "substruct_param_perf",
                "substructure": "Differential Pair",
                "parameter": "l2",
                "metric": "rms_noise_out",
                "direction": "increase_improves",
                "confidence": 0.7,
                "evidence_count": 8,
                "evidence_iters": [1, 40, 88],
                "topology": "5t_ota",
            },
            {
                "type": "substruct_param_perf",
                "substructure": "Differential Pair",
                "parameter": "w2",
                "metric": "output_swing",
                "direction": "negative",
                "confidence": 0.7,
                "evidence_count": 8,
                "evidence_iters": [29, 40, 61],
                "topology": "5t_ota",
            },
            {
                "type": "substruct_param_perf",
                "substructure": "Current Mirror (active load)",
                "parameter": "l3",
                "metric": "pm",
                "direction": "negative",
                "confidence": 0.7,
                "evidence_count": 8,
                "evidence_iters": [1, 29, 40],
                "topology": "5t_ota",
            },
            {
                "type": "substruct_param_perf",
                "substructure": "Current Mirror (active load)",
                "parameter": "w3",
                "metric": "pm",
                "direction": "increase_degrades",
                "confidence": 0.7,
                "evidence_count": 8,
                "evidence_iters": [1, 29, 40],
                "topology": "5t_ota",
            },
            {
                "type": "substruct_param_perf",
                "substructure": "Current Source",
                "parameter": "Idc",
                "metric": "power",
                "direction": "increase_degrades",
                "confidence": 0.9,
                "evidence_count": 10,
                "evidence_iters": [1, 29, 40],
                "topology": "5t_ota",
            },
            {
                "type": "substruct_param_perf",
                "substructure": "Current Source",
                "parameter": "Idc",
                "metric": "slew_rate_rise",
                "direction": "increase_improves",
                "confidence": 0.7,
                "evidence_count": 9,
                "evidence_iters": [1, 29, 40],
                "topology": "5t_ota",
            },
        ]
    }


def _role_perf_payload() -> dict:
    return {
        "facts": [
            {
                "type": "role_perf",
                "functional_role": "Main signal path (input transconductor + active load)",
                "metric": "output_swing",
                "influence": "significant",
                "confidence": 0.7,
                "evidence_count": 9,
                "evidence_iters": [1, 29, 40],
                "topology": "5t_ota",
            },
            {
                "type": "role_perf",
                "functional_role": "Main signal path (input transconductor + active load)",
                "metric": "rms_noise_out",
                "influence": "significant",
                "confidence": 0.7,
                "evidence_count": 8,
                "evidence_iters": [29, 40, 61],
                "topology": "5t_ota",
            },
            {
                "type": "role_perf",
                "functional_role": "Bias / reference generation (tail current bias)",
                "metric": "power",
                "influence": "dominant",
                "confidence": 0.9,
                "evidence_count": 10,
                "evidence_iters": [1, 29, 40],
                "topology": "5t_ota",
            },
            {
                "type": "role_perf",
                "functional_role": "Bias / reference generation (tail current bias)",
                "metric": "slew_rate_rise",
                "influence": "significant",
                "confidence": 0.7,
                "evidence_count": 8,
                "evidence_iters": [1, 29, 40],
                "topology": "5t_ota",
            },
        ]
    }


def _critical_heuristics_payload() -> dict:
    return {
        "heuristics": [
            {
                "case_name": "5t_ota",
                "condition": {"target_metrics": ["power"]},
                "heuristic": "Stabilize feasibility before optimizing power and preserve signal-path operating headroom.",
                "priority": "high",
                "scope": "both",
            },
            {
                "case_name": "5t_ota",
                "condition": {"target_metrics": ["cmrr"]},
                "heuristic": "Strengthen symmetry and bias robustness before attempting aggressive bandwidth optimization.",
                "priority": "high",
                "scope": "worker",
            },
            {
                "case_name": "5t_ota",
                "condition": {"target_metrics": ["pm"]},
                "heuristic": "Establish adequate loop stability before pursuing secondary speed improvements.",
                "priority": "medium",
                "scope": "planner",
            },
        ]
    }


class TestKBPipeline(unittest.TestCase):
    def test_run_kb_fact_extraction_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            settings = base / "5t_ota_settings.json"
            improving = base / "5t_ota_improving_designs.json"
            tagging = base / "5t_ota.json"

            settings.write_text(json.dumps(_settings_payload()), encoding="utf-8")
            improving.write_text(json.dumps([{"iter": 1}]), encoding="utf-8")
            tagging.write_text(json.dumps(_tagging_payload()), encoding="utf-8")

            with patch("agentic_sizing.kb.pipeline.create_structured_client") as create_client:
                client = create_client.return_value
                client.generate_structured.side_effect = [
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_perf_tradeoff_payload(),
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_substruct_param_perf_payload(),
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_role_perf_payload(),
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_critical_heuristics_payload(),
                        raw_text="{}",
                    ),
                ]

                result = run_kb_fact_extraction(
                    settings_path=str(settings),
                    improving_designs_path=str(improving),
                    tagging_path=str(tagging),
                    output_dir=str(base),
                    output_prefix="5t_ota",
                    heuristics_output_dir=str(base / "critical_heuristics"),
                )

            self.assertEqual(client.generate_structured.call_count, 4)
            schema_names = [
                call.args[0].schema_name for call in client.generate_structured.call_args_list
            ]
            self.assertEqual(
                schema_names,
                [
                    "kb_perf_tradeoff",
                    "kb_substruct_param_perf",
                    "kb_role_perf",
                    "critical_heuristics",
                ],
            )

            first_req = client.generate_structured.call_args_list[0].args[0]
            self.assertEqual(first_req.reasoning_effort, "low")

            self.assertEqual(len(result["perf_tradeoff"]["facts"]), 3)
            self.assertEqual(len(result["substruct_param_perf"]["facts"]), 8)
            self.assertEqual(len(result["role_perf"]["facts"]), 8)
            self.assertEqual(result["perf_tradeoff"]["facts"][0]["direction"], "unspecified")
            self.assertEqual(result["substruct_param_perf"]["facts"][0]["direction"], "unspecified")
            self.assertEqual(result["substruct_param_perf"]["facts"][0]["parameter"], "l")

            role_facts = result["role_perf"]["facts"]
            self.assertTrue(
                any(
                    fact["metric"] == "power"
                    and fact["functional_role"]
                    == "Main signal path (input transconductor + active load)"
                    and fact["influence"] == "significant"
                    and fact["evidence_count"] == 0
                    for fact in role_facts
                )
            )
            self.assertTrue(
                any(
                    fact["metric"] == "output_swing"
                    and fact["functional_role"] == "Bias / reference generation (tail current bias)"
                    and fact["influence"] == "weak"
                    and fact["evidence_count"] == 0
                    for fact in role_facts
                )
            )

            outputs = result["output_files"]
            self.assertTrue(Path(outputs["perf_tradeoff"]).exists())
            self.assertTrue(Path(outputs["substruct_param_perf"]).exists())
            self.assertTrue(Path(outputs["role_perf"]).exists())
            self.assertEqual(len(result["critical_heuristics"]), 3)
            self.assertTrue(Path(result["critical_heuristic_files"]["case"]).exists())
            self.assertTrue(Path(result["critical_heuristic_files"]["global"]).exists())

    def test_run_kb_fact_extraction_retries_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            settings = base / "5t_ota_settings.json"
            improving = base / "5t_ota_improving_designs.json"
            tagging = base / "5t_ota.json"

            settings.write_text(json.dumps(_settings_payload()), encoding="utf-8")
            improving.write_text(json.dumps([{"iter": 1}]), encoding="utf-8")
            tagging.write_text(json.dumps(_tagging_payload()), encoding="utf-8")

            bad_step2 = {
                "facts": [
                    {
                        "type": "substruct_param_perf",
                        "substructure": "Current Mirror",
                        "parameter": "l1",
                        "metric": "rms_noise_out",
                        "direction": "negative",
                        "confidence": 0.7,
                        "evidence_count": 2,
                        "evidence_iters": [1],
                        "topology": "5t_ota",
                    }
                ]
            }

            with patch("agentic_sizing.kb.pipeline.create_structured_client") as create_client:
                client = create_client.return_value
                client.generate_structured.side_effect = [
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_perf_tradeoff_payload(),
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=bad_step2,
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_substruct_param_perf_payload(),
                        raw_text="{}",
                    ),
                    StructuredGenerationResult(
                        provider="openai",
                        model="gpt-5.2",
                        output_json=_role_perf_payload(),
                        raw_text="{}",
                    ),
                ]

                result = run_kb_fact_extraction(
                    settings_path=str(settings),
                    improving_designs_path=str(improving),
                    tagging_path=str(tagging),
                    max_retries=1,
                    generate_heuristics=False,
                )

            self.assertEqual(len(result["substruct_param_perf"]["facts"]), 8)
            self.assertTrue(
                all(
                    fact["parameter"] in {"l", "w", "Idc"}
                    for fact in result["substruct_param_perf"]["facts"]
                )
            )
            self.assertEqual(client.generate_structured.call_count, 4)

    def test_run_kb_fact_extraction_retries_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            settings = base / "5t_ota_settings.json"
            improving = base / "5t_ota_improving_designs.json"
            tagging = base / "5t_ota.json"

            settings.write_text(json.dumps(_settings_payload()), encoding="utf-8")
            improving.write_text(json.dumps([{"iter": 1}]), encoding="utf-8")
            tagging.write_text(json.dumps(_tagging_payload()), encoding="utf-8")

            with patch("agentic_sizing.kb.pipeline.create_structured_client") as create_client:
                client = create_client.return_value
                client.generate_structured.return_value = StructuredGenerationResult(
                    provider="openai",
                    model="gpt-5.2",
                    output_json={"facts": []},
                    raw_text="{}",
                )

                with self.assertRaises(KBFactExtractionError):
                    run_kb_fact_extraction(
                        settings_path=str(settings),
                        improving_designs_path=str(improving),
                        tagging_path=str(tagging),
                        max_retries=0,
                        generate_heuristics=False,
                    )


if __name__ == "__main__":
    unittest.main()
