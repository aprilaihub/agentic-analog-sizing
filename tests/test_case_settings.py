from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
PACKAGE_ROOT = AGENTIC_SIZING_ROOT / "src" / "agentic_sizing"
from agentic_sizing.initialization.pipeline import run_initialize_pipeline
from agentic_sizing.llm.contract import StructuredGenerationResult
from agentic_sizing.specs.case_settings import materialize_case_settings_json


class _FakeLLMClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)

    def generate_structured(self, request):  # type: ignore[no-untyped-def]
        if not self.payloads:
            raise RuntimeError("No fake payload left")
        payload = self.payloads.pop(0)
        return StructuredGenerationResult(
            provider=request.provider,
            model=request.model,
            output_json=payload,
            raw_text=json.dumps(payload),
        )


def _planner_payload() -> dict:
    return {
        "role_execution_plan": [
            {
                "role_name": "Bias network",
                "priority_rank": 1,
                "importance_rationale": "Bias controls operating point and slew quickly.",
                "worker_instruction": "Set conservative bias values first.",
                "focus_metrics": ["cmrr", "slew_rate_rise"],
            },
            {
                "role_name": "Main signal path",
                "priority_rank": 2,
                "importance_rationale": "Main path sets gain/noise/stability envelope.",
                "worker_instruction": "Tune input/load dimensions for balanced headroom.",
                "focus_metrics": ["pm", "rms_noise_out"],
            },
        ]
    }


def _worker_bias_payload() -> dict:
    return {
        "role_name": "Bias network",
        "assignments": [
            {"name": "l1", "value": 1.2e-06, "reason": "moderate channel length"},
            {"name": "w1", "value": 2.2e-05, "reason": "balanced current density"},
            {"name": "Idc", "value": 4.5e-06, "reason": "mid bias current"},
        ],
        "rationale": "Bias-first initialization to stabilize operating point.",
    }


def _worker_main_payload() -> dict:
    return {
        "role_name": "Main signal path",
        "assignments": [
            {"name": "l2", "value": 1.4e-06, "reason": "gm-ro balance"},
            {"name": "w2", "value": 3.8e-05, "reason": "input pair transconductance"},
            {"name": "l3", "value": 1.1e-06, "reason": "load mirror compliance"},
            {"name": "w3", "value": 2.9e-05, "reason": "load current match"},
        ],
        "rationale": "Main-path sizing consistent with bias context.",
    }


class TestCaseSettings(unittest.TestCase):
    def test_materialize_case_settings_json_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "agenticSizing"
            yaml_dir = project_root / "agentic_sizing" / "simulator" / "yaml_settings"
            yaml_dir.mkdir(parents=True, exist_ok=True)
            source_yaml = (
                AGENTIC_SIZING_ROOT
                / "src"
                / "agentic_sizing"
                / "simulator"
                / "yaml_settings"
                / "current_mirror.yaml"
            )
            shutil.copyfile(source_yaml, yaml_dir / "current_mirror.yaml")

            with (
                patch("agentic_sizing.specs.case_settings.PROJECT_ROOT", project_root),
                patch(
                    "agentic_sizing.specs.case_settings.PACKAGE_ROOT",
                    project_root / "agentic_sizing",
                ),
            ):
                output_path = materialize_case_settings_json("current_mirror")

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["objective"]["name"], "power")
            self.assertEqual(payload["des_vars"]["N3"], [1, 10, 1])
            self.assertEqual(payload["dependent_vars"], [])
            self.assertEqual(payload["intentions"], [])
            self.assertIn("state_outputs", payload)

    def test_initialize_pipeline_uses_yaml_when_settings_json_missing(self) -> None:
        tagging_path = PACKAGE_ROOT / "tagging" / "tagging_output.example.json"
        kb_examples_dir = PACKAGE_ROOT / "kb"
        source_yaml = (
            AGENTIC_SIZING_ROOT
            / "src"
            / "agentic_sizing"
            / "simulator"
            / "yaml_settings"
            / "5t_ota.yaml"
        )

        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "agenticSizing"
            (project_root / "input" / "kb").mkdir(parents=True, exist_ok=True)
            (project_root / "output" / "tagging").mkdir(parents=True, exist_ok=True)
            (project_root / "output" / "kb" / "pillars").mkdir(parents=True, exist_ok=True)
            (project_root / "agentic_sizing" / "simulator" / "yaml_settings").mkdir(
                parents=True, exist_ok=True
            )

            shutil.copyfile(
                source_yaml,
                project_root / "agentic_sizing" / "simulator" / "yaml_settings" / "5t_ota.yaml",
            )
            shutil.copyfile(
                tagging_path, project_root / "output" / "tagging" / "5t_ota.tagging.json"
            )
            for suffix in ("perf_tradeoff", "substruct_param_perf", "role_perf"):
                shutil.copyfile(
                    kb_examples_dir / f"kb_{suffix}.example.json",
                    project_root / "output" / "kb" / "pillars" / f"global_kb_{suffix}.json",
                )

            record_path = Path(td) / "simulation_record.json"

            with (
                patch("agentic_sizing.initialization.support.PROJECT_ROOT", project_root),
                patch(
                    "agentic_sizing.kb.runtime_seed.PROJECT_ROOT",
                    project_root,
                ),
                patch("agentic_sizing.specs.case_settings.PROJECT_ROOT", project_root),
                patch(
                    "agentic_sizing.specs.case_settings.PACKAGE_ROOT",
                    project_root / "agentic_sizing",
                ),
            ):
                result = run_initialize_pipeline(
                    netlist_path="5t_ota",
                    simulation_record_path=str(record_path),
                    llm_client=_FakeLLMClient(
                        [_planner_payload(), _worker_bias_payload(), _worker_main_payload()]
                    ),
                    simulation_backend="mock",
                )

            generated_settings = project_root / "input" / "kb" / "5t_ota_settings.json"
            self.assertTrue(generated_settings.exists())
            self.assertEqual(result["case_name"], "5t_ota")
            self.assertEqual(result["record"]["iter"], 1)
            self.assertEqual(len(result["specs"]), len(result["perf_order"]))
