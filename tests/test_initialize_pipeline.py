from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.initialization.pipeline import build_functional_roles, run_initialize_pipeline
from agentic_sizing.llm.contract import StructuredGenerationResult


class _FakeLLMClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.call_count = 0

    def generate_structured(self, request):  # type: ignore[no-untyped-def]
        self.call_count += 1
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
                "importance_rationale": "Bias controls slew quickly.",
                "worker_instruction": "Set conservative bias values first.",
                "focus_metrics": ["slew_rate_rise"],
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


def _worker_bias_payload(offset: float = 0.0) -> dict:
    return {
        "role_name": "Bias network",
        "assignments": [
            {"name": "l1", "value": 1.2e-06 + offset * 1e-08, "reason": "moderate channel length"},
            {"name": "w1", "value": 2.2e-05 + offset * 1e-07, "reason": "balanced current density"},
            {"name": "Idc", "value": 4.5e-06 + offset * 1e-08, "reason": "mid bias current"},
        ],
        "rationale": "Bias-first initialization to stabilize operating point.",
    }


def _worker_main_payload(offset: float = 0.0) -> dict:
    return {
        "role_name": "Main signal path",
        "assignments": [
            {"name": "l2", "value": 1.4e-06 + offset * 1e-08, "reason": "gm-ro balance"},
            {
                "name": "w2",
                "value": 3.8e-05 + offset * 1e-07,
                "reason": "input pair transconductance",
            },
            {"name": "l3", "value": 1.1e-06 + offset * 1e-08, "reason": "load mirror compliance"},
            {"name": "w3", "value": 2.9e-05 + offset * 1e-07, "reason": "load current match"},
        ],
        "rationale": "Main-path sizing consistent with bias context.",
    }


class TestInitializePipeline(unittest.TestCase):
    def test_build_functional_roles_keeps_roles_without_design_variables_for_context(self) -> None:
        tagging_json = {
            "stage1": {
                "functional_roles": [
                    {"name": "Main signal path", "devices": ["M1"], "description": "..."},
                    {"name": "Feedback network", "devices": ["R0", "R1"], "description": "..."},
                ]
            },
            "stage2": {
                "roles": [
                    {
                        "name": "Main signal path",
                        "substructures": [
                            {
                                "type": "Gain stage",
                                "variables": [{"device": "M1", "design_variables": ["x"]}],
                            }
                        ],
                    },
                    {
                        "name": "Feedback network",
                        "substructures": [
                            {
                                "type": "Resistor divider",
                                "variables": [],
                            }
                        ],
                    },
                ]
            },
        }

        roles = build_functional_roles(
            tagging_json,
            kb_role_perf_json={"facts": []},
            fallback_metrics=["m1"],
            settings_json={"des_vars": {"x": [0.0, 1.0]}},
        )

        self.assertEqual(
            [role.role_name for role in roles], ["Main signal path", "Feedback network"]
        )
        self.assertEqual(roles[0].design_variables, ["x"])
        self.assertEqual(roles[1].design_variables, [])

    def test_pipeline_success_and_record_append(self) -> None:
        settings_path = AGENTIC_SIZING_ROOT / "input" / "kb" / "5t_ota_settings.json"
        tagging_path = AGENTIC_SIZING_ROOT / "output" / "tagging" / "5t_ota.tagging.json"
        pillars_dir = AGENTIC_SIZING_ROOT / "output" / "kb" / "pillars"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        expected_design_order = list(settings["des_vars"].keys())
        expected_perf_order = list(settings["responses"]["assembler"])

        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "agenticSizing"
            (project_root / "input" / "kb").mkdir(parents=True, exist_ok=True)
            (project_root / "output" / "tagging").mkdir(parents=True, exist_ok=True)
            (project_root / "output" / "kb" / "pillars").mkdir(parents=True, exist_ok=True)

            shutil.copyfile(settings_path, project_root / "input" / "kb" / "5t_ota_settings.json")
            shutil.copyfile(
                tagging_path, project_root / "output" / "tagging" / "5t_ota.tagging.json"
            )
            for suffix in ("perf_tradeoff", "substruct_param_perf", "role_perf"):
                shutil.copyfile(
                    pillars_dir / f"global_kb_{suffix}.json",
                    project_root / "output" / "kb" / "pillars" / f"global_kb_{suffix}.json",
                )

            record_path = Path(td) / "simulation_record.json"

            with (
                patch("agentic_sizing.initialization.support.PROJECT_ROOT", project_root),
                patch(
                    "agentic_sizing.kb.runtime_seed.PROJECT_ROOT",
                    project_root,
                ),
            ):
                client1 = _FakeLLMClient(
                    [_planner_payload(), _worker_bias_payload(), _worker_main_payload()]
                )
                result1 = run_initialize_pipeline(
                    netlist_path="5t_ota",
                    simulation_record_path=str(record_path),
                    llm_client=client1,
                    simulation_backend="mock",
                )

                client2 = _FakeLLMClient(
                    [_planner_payload(), _worker_bias_payload(), _worker_main_payload()]
                )
                result2 = run_initialize_pipeline(
                    netlist_path="5t_ota",
                    simulation_record_path=str(record_path),
                    llm_client=client2,
                    simulation_backend="mock",
                )

            records = json.loads(record_path.read_text(encoding="utf-8"))
            copied_files_exist = {
                key: Path(path_text).exists()
                for key, path_text in result1["kb_seed_result"]["copied_files"].items()
            }

        self.assertEqual(result1["case_name"], "5t_ota")
        self.assertEqual(result1["record"]["iter"], 1)
        self.assertEqual(result2["record"]["iter"], 2)
        self.assertEqual([item["iter"] for item in records], [1, 2])

        self.assertEqual(result1["design_var_order"], expected_design_order)
        self.assertEqual(result1["perf_order"], expected_perf_order)

        self.assertEqual(len(result1["record"]["parameters"]), len(expected_design_order))
        self.assertEqual(len(result1["record"]["performance"]), len(expected_perf_order))

        self.assertEqual(set(result1["initial_design_vars"].keys()), set(expected_design_order))
        self.assertEqual(set(result1["initial_perfs"].keys()), set(expected_perf_order))

        self.assertGreaterEqual(len(result1["functional_roles"]), 2)
        self.assertEqual(len(result1["specs"]), len(expected_perf_order))
        self.assertEqual(result1["kb_seed_result"]["seed_name"], "global")
        self.assertTrue(copied_files_exist["perf_tradeoff"])
        self.assertTrue(copied_files_exist["substruct_param_perf"])
        self.assertTrue(copied_files_exist["role_perf"])

    def test_pipeline_can_start_from_multiple_initial_samples(self) -> None:
        settings_path = AGENTIC_SIZING_ROOT / "input" / "kb" / "5t_ota_settings.json"
        tagging_path = AGENTIC_SIZING_ROOT / "output" / "tagging" / "5t_ota.tagging.json"
        pillars_dir = AGENTIC_SIZING_ROOT / "output" / "kb" / "pillars"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        expected_design_order = list(settings["des_vars"].keys())
        expected_perf_order = list(settings["responses"]["assembler"])

        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "agenticSizing"
            (project_root / "input" / "kb").mkdir(parents=True, exist_ok=True)
            (project_root / "output" / "tagging").mkdir(parents=True, exist_ok=True)
            (project_root / "output" / "kb" / "pillars").mkdir(parents=True, exist_ok=True)

            shutil.copyfile(settings_path, project_root / "input" / "kb" / "5t_ota_settings.json")
            shutil.copyfile(
                tagging_path, project_root / "output" / "tagging" / "5t_ota.tagging.json"
            )
            for suffix in ("perf_tradeoff", "substruct_param_perf", "role_perf"):
                shutil.copyfile(
                    pillars_dir / f"global_kb_{suffix}.json",
                    project_root / "output" / "kb" / "pillars" / f"global_kb_{suffix}.json",
                )

            record_path = Path(td) / "simulation_record.json"

            with (
                patch("agentic_sizing.initialization.support.PROJECT_ROOT", project_root),
                patch(
                    "agentic_sizing.kb.runtime_seed.PROJECT_ROOT",
                    project_root,
                ),
            ):
                client = _FakeLLMClient(
                    [
                        _planner_payload(),
                        _worker_bias_payload(0),
                        _worker_main_payload(0),
                        _worker_bias_payload(1),
                        _worker_main_payload(1),
                        _worker_bias_payload(2),
                        _worker_main_payload(2),
                    ]
                )
                result = run_initialize_pipeline(
                    netlist_path="5t_ota",
                    simulation_record_path=str(record_path),
                    llm_client=client,
                    simulation_backend="mock",
                    initial_sample_count=3,
                )

            records = json.loads(record_path.read_text(encoding="utf-8"))

        self.assertEqual(result["initial_sample_count"], 3)
        self.assertEqual(len(result["initial_samples"]), 3)
        self.assertEqual([item["iter"] for item in records], [1, 2, 3])
        self.assertIn(result["selected_initial_sample_index"], {0, 1, 2})
        self.assertEqual(
            result["record"]["iter"],
            result["initial_samples"][result["selected_initial_sample_index"]]["record"]["iter"],
        )
        self.assertNotEqual(
            result["initial_samples"][0]["parameters"], result["initial_samples"][1]["parameters"]
        )
        self.assertEqual(set(result["initial_design_vars"].keys()), set(expected_design_order))
        self.assertEqual(set(result["initial_perfs"].keys()), set(expected_perf_order))


if __name__ == "__main__":
    unittest.main()
