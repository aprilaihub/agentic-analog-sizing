from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.initialization.initialize_worker import (
    InitializeWorkerError,
    run_initialize_worker,
)
from agentic_sizing.llm.contract import StructuredGenerationResult


class _FakeLLMClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.call_count = 0
        self.last_request = None

    def generate_structured(self, request):  # type: ignore[no-untyped-def]
        self.call_count += 1
        self.last_request = request
        if not self.payloads:
            raise RuntimeError("No fake payload left")
        payload = self.payloads.pop(0)
        return StructuredGenerationResult(
            provider=request.provider,
            model=request.model,
            output_json=payload,
            raw_text=json.dumps(payload),
        )


class TestInitializeWorker(unittest.TestCase):
    def _write_inputs(self, base: Path) -> dict[str, str]:
        settings_path = base / "settings.json"
        tagging_path = base / "tagging.json"
        design_specs_path = base / "design_specs.json"

        settings_path.write_text(
            json.dumps(
                {
                    "des_vars": {
                        "x": [0.0, 10.0, 0],
                        "y": [1.0, 9.0, 1],
                    }
                }
            ),
            encoding="utf-8",
        )

        tagging_path.write_text(
            json.dumps(
                {
                    "stage2": {
                        "roles": [
                            {
                                "name": "Role A",
                                "substructures": [
                                    {
                                        "type": "Block",
                                        "devices": ["M1"],
                                        "variables": [
                                            {
                                                "device": "M1",
                                                "design_variables": ["x", "y"],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        design_specs_path.write_text(json.dumps({"performance_specs": []}), encoding="utf-8")

        return {
            "settings_path": str(settings_path),
            "tagging_path": str(tagging_path),
            "design_specs_path": str(design_specs_path),
        }

    def test_success(self) -> None:
        payload = {
            "role_name": "Role A",
            "assignments": [
                {"name": "x", "value": 4.2, "reason": "center"},
                {"name": "y", "value": 7.0, "reason": "int-like"},
            ],
            "rationale": "Balanced init.",
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([payload])

            result = run_initialize_worker(
                role_name="Role A",
                worker_instruction="Set initial values.",
                prior_context=[],
                llm_client=client,
                **paths,
            )

        self.assertEqual(client.call_count, 1)
        self.assertEqual(result["role_name"], "Role A")
        self.assertEqual(len(result["assignments"]), 2)

    def test_retry_then_success(self) -> None:
        bad = {
            "role_name": "Role A",
            "assignments": [
                {"name": "x", "value": 99.0, "reason": "out of range"},
                {"name": "y", "value": 8.0, "reason": "ok"},
            ],
            "rationale": "bad first",
        }
        good = {
            "role_name": "Role A",
            "assignments": [
                {"name": "x", "value": 3.0, "reason": "ok"},
                {"name": "y", "value": 8.0, "reason": "ok"},
            ],
            "rationale": "good second",
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([bad, good])

            result = run_initialize_worker(
                role_name="Role A",
                worker_instruction="Set initial values.",
                prior_context=[{"role_name": "Role 0", "assignments": []}],
                llm_client=client,
                max_retries=1,
                **paths,
            )

        self.assertEqual(client.call_count, 2)
        self.assertEqual(result["role_name"], "Role A")

    def test_disable_kb_input_uses_empty_facts_without_loading_file(self) -> None:
        payload = {
            "role_name": "Role A",
            "assignments": [
                {"name": "x", "value": 4.2, "reason": "center"},
                {"name": "y", "value": 7.0, "reason": "int-like"},
            ],
            "rationale": "Balanced init.",
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([payload])

            run_initialize_worker(
                role_name="Role A",
                worker_instruction="Set initial values.",
                prior_context=[],
                kb_substruct_param_perf_path=str(Path(td) / "missing.json"),
                enable_kb_input=False,
                llm_client=client,
                **paths,
            )

        prompt = client.last_request.messages[1].content
        self.assertNotIn("Interpreted KB substructure-parameter-performance hints:", prompt)
        self.assertNotIn("Retrieved critical heuristics for this case:", prompt)

    def test_prompt_includes_critical_heuristics(self) -> None:
        payload = {
            "role_name": "Role A",
            "assignments": [
                {"name": "x", "value": 4.2, "reason": "center"},
                {"name": "y", "value": 7.0, "reason": "int-like"},
            ],
            "rationale": "Balanced init.",
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([payload])

            with patch(
                "agentic_sizing.initialization.initialize_worker.retrieve_critical_heuristics",
                return_value=["Prefer conservative x during initialization."],
            ):
                run_initialize_worker(
                    role_name="Role A",
                    worker_instruction="Set initial values.",
                    prior_context=[],
                    llm_client=client,
                    **paths,
                )

        prompt = client.last_request.messages[1].content
        self.assertIn("Retrieved critical heuristics for this case:", prompt)
        self.assertIn("Prefer conservative x during initialization.", prompt)

    def test_retry_exhausted(self) -> None:
        bad = {
            "role_name": "Role A",
            "assignments": [
                {"name": "x", "value": 99.0, "reason": "out of range"},
                {"name": "y", "value": 8.0, "reason": "ok"},
            ],
            "rationale": "bad",
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([bad])

            with self.assertRaises(InitializeWorkerError):
                run_initialize_worker(
                    role_name="Role A",
                    worker_instruction="Set initial values.",
                    prior_context=[],
                    llm_client=client,
                    max_retries=0,
                    **paths,
                )

    def test_synthetic_testbench_and_bias_controls_role_uses_unowned_settings_variables(
        self,
    ) -> None:
        payload = {
            "role_name": "Testbench and bias controls",
            "assignments": [
                {"name": "Cf", "value": 5.0e-13, "reason": "mid compensation capacitance"},
                {"name": "VPC", "value": 0.9, "reason": "mid bias control"},
                {"name": "VNC", "value": 0.9, "reason": "mid bias control"},
            ],
            "rationale": "Initialize unowned testbench and bias settings conservatively.",
        }

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            settings_path = base / "settings.json"
            tagging_path = base / "tagging.json"
            design_specs_path = base / "design_specs.json"

            settings_path.write_text(
                json.dumps(
                    {
                        "des_vars": {
                            "x": [0.0, 10.0, 0],
                            "Cf": [50e-15, 2e-12, 0],
                            "VPC": [0.0, 1.8, 0],
                            "VNC": [0.0, 1.8, 0],
                        }
                    }
                ),
                encoding="utf-8",
            )
            tagging_path.write_text(
                json.dumps(
                    {
                        "stage2": {
                            "roles": [
                                {
                                    "name": "Role A",
                                    "substructures": [
                                        {
                                            "type": "Block",
                                            "devices": ["M1"],
                                            "variables": [
                                                {"device": "M1", "design_variables": ["x"]}
                                            ],
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            design_specs_path.write_text(json.dumps({"performance_specs": []}), encoding="utf-8")

            result = run_initialize_worker(
                role_name="Testbench and bias controls",
                worker_instruction="Initialize unowned controls.",
                settings_path=str(settings_path),
                tagging_path=str(tagging_path),
                design_specs_path=str(design_specs_path),
                prior_context=[],
                llm_client=_FakeLLMClient([payload]),
            )

        assigned_names = {item["name"] for item in result["assignments"]}
        self.assertEqual(assigned_names, {"Cf", "VPC", "VNC"})

    def test_objective_metric_hidden_from_initialization_prompt(self) -> None:
        payload = {
            "role_name": "Role A",
            "assignments": [
                {"name": "x", "value": 4.2, "reason": "center"},
                {"name": "y", "value": 7.0, "reason": "int-like"},
            ],
            "rationale": "Feasibility-first init.",
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            Path(paths["settings_path"]).write_text(
                json.dumps(
                    {
                        "des_vars": {
                            "x": [0.0, 10.0, 0],
                            "y": [1.0, 9.0, 1],
                        },
                        "responses": {"assembler": ["power", "pm"]},
                        "outputs": {
                            "power": [1e-3, "target", 1.0, "*value"],
                            "pm": [60.0, "min", 1.0, "*value"],
                        },
                        "objective": {"name": "power", "minormax": "min"},
                    }
                ),
                encoding="utf-8",
            )
            Path(paths["design_specs_path"]).write_text(
                json.dumps(
                    {
                        "objective": {"metric": "power", "sense": "min"},
                        "performance_specs": [
                            {"name": "power", "index": 0, "method": "target", "threshold": 1e-3},
                            {"name": "pm", "index": 1, "method": "min", "threshold": 60.0},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            client = _FakeLLMClient([payload])

            run_initialize_worker(
                role_name="Role A",
                worker_instruction="Set initial values.",
                prior_context=[],
                llm_client=client,
                **paths,
            )

        prompt = client.last_request.messages[-1].content
        self.assertNotIn('"power"', prompt)
        self.assertIn("objective_hidden_until_feasible", prompt)


if __name__ == "__main__":
    unittest.main()
