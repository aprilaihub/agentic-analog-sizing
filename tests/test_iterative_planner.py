from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
PACKAGE_ROOT = AGENTIC_SIZING_ROOT / "src" / "agentic_sizing"
from agentic_sizing.iteration.context import extract_stage1_role_names
from agentic_sizing.iteration.iterative_planner import run_iterative_planner
from agentic_sizing.llm.contract import StructuredGenerationResult


class _FakeLLMClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls = 0
        self.requests = []

    def generate_structured(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.requests.append(request)
        if not self.payloads:
            raise RuntimeError("No fake payload left")
        payload = self.payloads.pop(0)
        return StructuredGenerationResult(
            provider=request.provider,
            model=request.model,
            output_json=payload,
            raw_text=json.dumps(payload),
        )


def _build_simulation_record(path: Path) -> None:
    improving_path = AGENTIC_SIZING_ROOT / "input" / "kb" / "5t_ota_improving_designs.json"
    improving = json.loads(improving_path.read_text(encoding="utf-8"))
    first = improving[0]
    record = [
        {
            "iter": 1,
            "parameters": first["parameters"],
            "performance": first["performance"],
        }
    ]
    path.write_text(json.dumps(record, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _current_predicted_perfs_with_cmrr_unsat() -> dict[str, float]:
    design_specs_path = PACKAGE_ROOT / "specs" / "5t_ota_design_specs.example.json"
    payload = json.loads(design_specs_path.read_text(encoding="utf-8"))

    result: dict[str, float] = {}
    for item in payload["performance_specs"]:
        name = item["name"]
        method = item["method"]
        threshold = float(item["threshold"])
        if method == "min":
            result[name] = threshold + 0.1
        elif method == "max":
            result[name] = threshold - 0.1
        else:
            result[name] = threshold

    result["cmrr"] = 70.0
    return result


class TestIterativePlanner(unittest.TestCase):
    def test_allowed_roles_exclude_stage2_roles_without_design_variables(self) -> None:
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

        roles = extract_stage1_role_names(tagging_json, {"des_vars": {"x": [0.0, 1.0]}})

        self.assertEqual(roles, {"Main signal path"})

    def test_planner_success(self) -> None:
        payload = {
            "state_action": "continue_current",
            "target_metric": "cmrr",
            "selected_role_name": "Main signal path",
            "worker_instruction": "Increase main-path gm capability while preserving PM.",
            "selection_rationale": "cmrr is unsatisfied and main path has strongest leverage.",
            "recovery_rationale": "Current trajectory is acceptable; continue from the live state.",
            "focus_kb_evidence": [
                "role_perf: main path impacts cmrr-adjacent gain behavior",
                "tradeoff: keep PM stable while improving cmrr",
            ],
        }

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            result = run_iterative_planner(
                case_name="5t_ota",
                simulation_record_path=str(simulation_record_path),
                current_predicted_perfs=_current_predicted_perfs_with_cmrr_unsat(),
                llm_client=_FakeLLMClient([payload]),
            )

        self.assertEqual(result["target_metric"], "cmrr")
        self.assertEqual(result["selected_role_name"], "Main signal path")
        self.assertIn("cmrr", result["unsatisfied_metrics"])

    def test_planner_prompt_includes_local_summary(self) -> None:
        payload = {
            "state_action": "continue_current",
            "target_metric": "cmrr",
            "selected_role_name": "Bias network",
            "worker_instruction": "Tune the bias role for cmrr.",
            "selection_rationale": "Bias is the best next fallback role.",
            "recovery_rationale": "No revert is needed for this planner step.",
            "focus_kb_evidence": ["role_perf: bias can influence cmrr context"],
        }
        fake = _FakeLLMClient([payload])

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            run_iterative_planner(
                case_name="5t_ota",
                simulation_record_path=str(simulation_record_path),
                current_predicted_perfs=_current_predicted_perfs_with_cmrr_unsat(),
                llm_client=fake,
            )

        prompt = fake.requests[0].messages[1].content
        self.assertIn("Strategic local summary:", prompt)
        self.assertIn('"phase"', prompt)
        self.assertIn('"priority_metrics"', prompt)
        self.assertIn("Choose exactly one functional role worker to dispatch", prompt)
        self.assertIn(
            "Use the strategic local summary as the primary interpretation of the current run state.",
            prompt,
        )
        self.assertIn("state_action", prompt)
        self.assertIn("revert_to_best_known", prompt)

    def test_planner_retries_on_invalid_role(self) -> None:
        invalid = {
            "state_action": "continue_current",
            "target_metric": "cmrr",
            "selected_role_name": "Unknown role",
            "worker_instruction": "bad",
            "selection_rationale": "bad",
            "recovery_rationale": "bad",
            "focus_kb_evidence": ["bad"],
        }
        valid = {
            "state_action": "continue_current",
            "target_metric": "cmrr",
            "selected_role_name": "Bias network",
            "worker_instruction": "Tune bias mirror for cmrr margin.",
            "selection_rationale": "Bias role is valid and actionable for this step.",
            "recovery_rationale": "Continue current because the invalid first response was rejected.",
            "focus_kb_evidence": ["role_perf: bias influences cmrr context"],
        }
        fake = _FakeLLMClient([invalid, valid])

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            result = run_iterative_planner(
                case_name="5t_ota",
                simulation_record_path=str(simulation_record_path),
                current_predicted_perfs=_current_predicted_perfs_with_cmrr_unsat(),
                max_retries=1,
                llm_client=fake,
            )

        self.assertEqual(fake.calls, 2)
        self.assertEqual(result["selected_role_name"], "Bias network")

    def test_disable_kb_input_uses_empty_filtered_facts(self) -> None:
        payload = {
            "state_action": "continue_current",
            "target_metric": "cmrr",
            "selected_role_name": "Bias network",
            "worker_instruction": "Tune the bias role for cmrr.",
            "selection_rationale": "Bias is the best next fallback role.",
            "recovery_rationale": "No revert is needed for this planner step.",
            "focus_kb_evidence": ["No KB facts supplied in this ablation run."],
        }
        fake = _FakeLLMClient([payload])

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            run_iterative_planner(
                case_name="5t_ota",
                simulation_record_path=str(simulation_record_path),
                current_predicted_perfs=_current_predicted_perfs_with_cmrr_unsat(),
                enable_kb_input=False,
                max_retries=0,
                llm_client=fake,
            )

        prompt = fake.requests[0].messages[1].content
        self.assertNotIn("Interpreted role-performance KB hints:", prompt)
        self.assertNotIn("Interpreted performance-tradeoff KB hints:", prompt)
        self.assertNotIn(
            "Retrieved critical heuristics for this case and current metric set:", prompt
        )

    def test_planner_prompt_includes_critical_heuristics_section(self) -> None:
        payload = {
            "state_action": "continue_current",
            "target_metric": "cmrr",
            "selected_role_name": "Bias network",
            "worker_instruction": "Tune the bias role for cmrr.",
            "selection_rationale": "Bias is the best next fallback role.",
            "recovery_rationale": "No revert is needed for this planner step.",
            "focus_kb_evidence": ["critical heuristic: prioritize the bias current lever first"],
        }
        fake = _FakeLLMClient([payload])

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            with patch(
                "agentic_sizing.iteration.iterative_planner.retrieve_critical_heuristics",
                return_value=["Increase Idc (not Idc2 or Idc3) can improve slew rates."],
            ):
                run_iterative_planner(
                    case_name="5t_ota",
                    simulation_record_path=str(simulation_record_path),
                    current_predicted_perfs=_current_predicted_perfs_with_cmrr_unsat(),
                    llm_client=fake,
                )

        prompt = fake.requests[0].messages[1].content
        self.assertIn("Retrieved critical heuristics for this case and current metric set:", prompt)
        self.assertIn("Increase Idc (not Idc2 or Idc3) can improve slew rates.", prompt)


if __name__ == "__main__":
    unittest.main()
