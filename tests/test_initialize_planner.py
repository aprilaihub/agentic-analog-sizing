from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.initialization.initialize_planner import (
    InitializePlannerError,
    run_initialize_planner,
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


class TestInitializePlanner(unittest.TestCase):
    def _write_inputs(self, base: Path) -> dict[str, str]:
        settings_path = base / "settings.json"
        tagging_path = base / "tagging.json"
        kb_perf_tradeoff_path = base / "kb_perf_tradeoff.json"
        kb_role_perf_path = base / "kb_role_perf.json"
        design_specs_path = base / "design_specs.json"

        settings_path.write_text(
            json.dumps({"des_vars": {}, "responses": {"assembler": ["m1", "m2"]}}), encoding="utf-8"
        )
        tagging_path.write_text(
            json.dumps(
                {
                    "stage1": {
                        "functional_roles": [
                            {"name": "Role A", "devices": ["M1"], "description": "..."},
                            {"name": "Role B", "devices": ["M2"], "description": "..."},
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        kb_perf_tradeoff_path.write_text(json.dumps({"facts": []}), encoding="utf-8")
        kb_role_perf_path.write_text(json.dumps({"facts": []}), encoding="utf-8")
        design_specs_path.write_text(
            json.dumps(
                {
                    "performance_specs": [
                        {"name": "m1"},
                        {"name": "m2"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        return {
            "settings_path": str(settings_path),
            "tagging_path": str(tagging_path),
            "kb_perf_tradeoff_path": str(kb_perf_tradeoff_path),
            "kb_role_perf_path": str(kb_role_perf_path),
            "design_specs_path": str(design_specs_path),
        }

    def test_success(self) -> None:
        payload = {
            "role_execution_plan": [
                {
                    "role_name": "Role A",
                    "priority_rank": 1,
                    "importance_rationale": "A first",
                    "worker_instruction": "Set Role A vars conservatively.",
                    "focus_metrics": ["m1"],
                },
                {
                    "role_name": "Role B",
                    "priority_rank": 2,
                    "importance_rationale": "B second",
                    "worker_instruction": "Set Role B vars aggressively.",
                    "focus_metrics": ["m2"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([payload])

            result = run_initialize_planner(
                **paths,
                llm_client=client,
            )

        self.assertEqual(client.call_count, 1)
        self.assertEqual([item["priority_rank"] for item in result["role_execution_plan"]], [1, 2])

    def test_retry_then_success(self) -> None:
        bad_payload = {
            "role_execution_plan": [
                {
                    "role_name": "Unknown Role",
                    "priority_rank": 1,
                    "importance_rationale": "bad",
                    "worker_instruction": "bad",
                    "focus_metrics": ["m1"],
                }
            ]
        }
        good_payload = {
            "role_execution_plan": [
                {
                    "role_name": "Role A",
                    "priority_rank": 1,
                    "importance_rationale": "A first",
                    "worker_instruction": "A",
                    "focus_metrics": ["m1"],
                },
                {
                    "role_name": "Role B",
                    "priority_rank": 2,
                    "importance_rationale": "B second",
                    "worker_instruction": "B",
                    "focus_metrics": ["m2"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([bad_payload, good_payload])

            result = run_initialize_planner(
                **paths,
                llm_client=client,
                max_retries=1,
            )

        self.assertEqual(client.call_count, 2)
        self.assertEqual(len(result["role_execution_plan"]), 2)

    def test_retry_exhausted(self) -> None:
        bad_payload = {
            "role_execution_plan": [
                {
                    "role_name": "Unknown Role",
                    "priority_rank": 1,
                    "importance_rationale": "bad",
                    "worker_instruction": "bad",
                    "focus_metrics": ["m1"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([bad_payload])

            with self.assertRaises(InitializePlannerError):
                run_initialize_planner(
                    **paths,
                    llm_client=client,
                    max_retries=0,
                )

    def test_objective_metric_hidden_from_initialization_prompt(self) -> None:
        payload = {
            "role_execution_plan": [
                {
                    "role_name": "Role A",
                    "priority_rank": 1,
                    "importance_rationale": "A first",
                    "worker_instruction": "Set Role A for feasibility.",
                    "focus_metrics": ["pm"],
                },
                {
                    "role_name": "Role B",
                    "priority_rank": 2,
                    "importance_rationale": "B second",
                    "worker_instruction": "Set Role B for feasibility.",
                    "focus_metrics": ["ugb"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            Path(paths["settings_path"]).write_text(
                json.dumps(
                    {
                        "des_vars": {},
                        "responses": {"assembler": ["power", "pm", "ugb"]},
                        "outputs": {
                            "power": [1e-3, "target", 1.0, "*value"],
                            "pm": [60.0, "min", 1.0, "*value"],
                            "ugb": [1e7, "min", 1.0, "*value"],
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
                            {"name": "ugb", "index": 2, "method": "min", "threshold": 1e7},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            client = _FakeLLMClient([payload])

            run_initialize_planner(
                **paths,
                llm_client=client,
            )

        prompt = client.last_request.messages[-1].content
        self.assertNotIn('"power"', prompt)
        self.assertIn("objective_hidden_until_feasible", prompt)

    def test_disable_kb_input_uses_empty_facts_without_loading_files(self) -> None:
        payload = {
            "role_execution_plan": [
                {
                    "role_name": "Role A",
                    "priority_rank": 1,
                    "importance_rationale": "A first",
                    "worker_instruction": "Set Role A vars conservatively.",
                    "focus_metrics": ["m1"],
                },
                {
                    "role_name": "Role B",
                    "priority_rank": 2,
                    "importance_rationale": "B second",
                    "worker_instruction": "Set Role B vars aggressively.",
                    "focus_metrics": ["m2"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([payload])

            run_initialize_planner(
                settings_path=paths["settings_path"],
                tagging_path=paths["tagging_path"],
                kb_perf_tradeoff_path=str(Path(td) / "missing_tradeoff.json"),
                kb_role_perf_path=str(Path(td) / "missing_role.json"),
                design_specs_path=paths["design_specs_path"],
                enable_kb_input=False,
                llm_client=client,
            )

        prompt = client.last_request.messages[-1].content
        self.assertNotIn("Interpreted KB perf-tradeoff hints:", prompt)
        self.assertNotIn("Interpreted KB role-performance hints:", prompt)
        self.assertNotIn("Retrieved critical heuristics for this case:", prompt)

    def test_prompt_includes_critical_heuristics(self) -> None:
        payload = {
            "role_execution_plan": [
                {
                    "role_name": "Role A",
                    "priority_rank": 1,
                    "importance_rationale": "A first",
                    "worker_instruction": "Set Role A vars conservatively.",
                    "focus_metrics": ["m1"],
                },
                {
                    "role_name": "Role B",
                    "priority_rank": 2,
                    "importance_rationale": "B second",
                    "worker_instruction": "Set Role B vars aggressively.",
                    "focus_metrics": ["m2"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([payload])

            with patch(
                "agentic_sizing.initialization.initialize_planner.retrieve_critical_heuristics",
                return_value=["Prefer Role A first for m1."],
            ):
                run_initialize_planner(
                    **paths,
                    llm_client=client,
                )

        prompt = client.last_request.messages[-1].content
        self.assertIn("Retrieved critical heuristics for this case:", prompt)
        self.assertIn("Prefer Role A first for m1.", prompt)

    def test_disable_heuristics_keeps_other_kb_input(self) -> None:
        payload = {
            "role_execution_plan": [
                {
                    "role_name": "Role A",
                    "priority_rank": 1,
                    "importance_rationale": "A first",
                    "worker_instruction": "Set Role A vars.",
                    "focus_metrics": ["m1"],
                },
                {
                    "role_name": "Role B",
                    "priority_rank": 2,
                    "importance_rationale": "B second",
                    "worker_instruction": "Set Role B vars.",
                    "focus_metrics": ["m2"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            client = _FakeLLMClient([payload])
            with patch(
                "agentic_sizing.initialization.initialize_planner.retrieve_critical_heuristics"
            ) as retrieve:
                run_initialize_planner(
                    **paths,
                    enable_kb_input=True,
                    enable_heuristics=False,
                    llm_client=client,
                )

        prompt = client.last_request.messages[-1].content
        retrieve.assert_not_called()
        self.assertIn("Interpreted KB perf-tradeoff hints:", prompt)
        self.assertIn("Interpreted KB role-performance hints:", prompt)
        self.assertNotIn("Retrieved critical heuristics for this case:", prompt)

    def test_planner_excludes_stage2_roles_without_design_variables(self) -> None:
        payload = {
            "role_execution_plan": [
                {
                    "role_name": "Role A",
                    "priority_rank": 1,
                    "importance_rationale": "Only editable role.",
                    "worker_instruction": "Set Role A variables.",
                    "focus_metrics": ["m1"],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            Path(paths["settings_path"]).write_text(
                json.dumps(
                    {
                        "des_vars": {"x": [0.0, 1.0]},
                        "responses": {"assembler": ["m1"]},
                    }
                ),
                encoding="utf-8",
            )
            Path(paths["tagging_path"]).write_text(
                json.dumps(
                    {
                        "stage1": {
                            "functional_roles": [
                                {"name": "Role A", "devices": ["M1"], "description": "..."},
                                {
                                    "name": "Feedback network",
                                    "devices": ["R0", "R1"],
                                    "description": "...",
                                },
                            ]
                        },
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
                                },
                                {
                                    "name": "Feedback network",
                                    "substructures": [
                                        {
                                            "type": "Resistor divider",
                                            "devices": ["R0", "R1"],
                                            "variables": [],
                                        }
                                    ],
                                },
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            Path(paths["design_specs_path"]).write_text(
                json.dumps({"performance_specs": [{"name": "m1"}]}),
                encoding="utf-8",
            )
            client = _FakeLLMClient([payload])

            result = run_initialize_planner(
                **paths,
                llm_client=client,
            )

        prompt = client.last_request.messages[-1].content
        self.assertEqual([item["role_name"] for item in result["role_execution_plan"]], ["Role A"])
        self.assertIn('"Role A"', prompt)
        self.assertNotIn(
            '"Feedback network"',
            prompt.split("Allowed roles:", 1)[1].split("Allowed metrics:", 1)[0],
        )

    def test_prompt_trims_tagging_evidence_and_design_spec_bookkeeping(self) -> None:
        payload = {
            "role_execution_plan": [
                {
                    "role_name": "Role A",
                    "priority_rank": 1,
                    "importance_rationale": "A first",
                    "worker_instruction": "Set Role A vars conservatively.",
                    "focus_metrics": ["m1"],
                },
                {
                    "role_name": "Role B",
                    "priority_rank": 2,
                    "importance_rationale": "B second",
                    "worker_instruction": "Set Role B vars aggressively.",
                    "focus_metrics": ["m2"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            paths = self._write_inputs(Path(td))
            Path(paths["tagging_path"]).write_text(
                json.dumps(
                    {
                        "stage1": {
                            "functional_roles": [
                                {"name": "Role A", "devices": ["M1"], "description": "..."},
                                {"name": "Role B", "devices": ["M2"], "description": "..."},
                            ]
                        },
                        "stage2": {
                            "roles": [
                                {
                                    "name": "Role A",
                                    "substructures": [
                                        {
                                            "type": "Bias current source",
                                            "devices": ["M1"],
                                            "evidence": "verbose structural explanation",
                                        }
                                    ],
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            Path(paths["design_specs_path"]).write_text(
                json.dumps(
                    {
                        "performance_specs": [
                            {
                                "name": "m1",
                                "index": 0,
                                "method": "min",
                                "threshold": 1.0,
                                "weight": 1.0,
                                "calc_expr": "*value",
                            },
                            {
                                "name": "m2",
                                "index": 1,
                                "method": "min",
                                "threshold": 2.0,
                                "weight": 1.0,
                                "calc_expr": "*value",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            client = _FakeLLMClient([payload])

            run_initialize_planner(
                **paths,
                llm_client=client,
            )

        prompt = client.last_request.messages[-1].content
        self.assertNotIn('"evidence":', prompt)
        self.assertNotIn('"calc_expr":', prompt)
        self.assertNotIn('"weight":', prompt)
        self.assertIn('"threshold": 1.0', prompt)


if __name__ == "__main__":
    unittest.main()
