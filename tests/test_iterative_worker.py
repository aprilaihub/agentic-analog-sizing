from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
PACKAGE_ROOT = AGENTIC_SIZING_ROOT / "src" / "agentic_sizing"
from agentic_sizing.iteration.context import build_worker_context
from agentic_sizing.iteration.iterative_worker import run_iterative_worker
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
    order = _design_var_order()
    design = _baseline_design()
    record = [
        {
            "iter": 1,
            "parameters": [float(design[name]) for name in order],
            "performance": _synthetic_performance_vector(design),
        }
    ]
    path.write_text(json.dumps(record, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _metric_names() -> list[str]:
    specs_path = PACKAGE_ROOT / "specs" / "5t_ota_design_specs.example.json"
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    return [item["name"] for item in sorted(specs["performance_specs"], key=lambda x: x["index"])]


def _settings_json() -> dict:
    settings_path = AGENTIC_SIZING_ROOT / "input" / "kb" / "5t_ota_settings.json"
    return json.loads(settings_path.read_text(encoding="utf-8"))


def _design_var_order() -> list[str]:
    return list(_settings_json()["des_vars"].keys())


def _perf_order() -> list[str]:
    return list(_settings_json()["responses"]["assembler"])


def _baseline_design() -> dict[str, float]:
    baseline = {}
    for name, bounds in _settings_json()["des_vars"].items():
        lower = float(bounds[0])
        upper = float(bounds[1])
        baseline[name] = 0.5 * (lower + upper)
    return baseline


def _synthetic_performance_vector(design: dict[str, float]) -> list[float]:
    idc = float(design["Idc"])
    l1 = float(design["l1"])
    w1 = float(design["w1"])
    perfs = {
        "power": 7.0e-05 + 6.0 * idc + 0.02 * w1,
        "cmrr": 87.0 + 2.5 * (l1 / 1.0e-06) - 0.2 * (idc / 1.0e-06),
        "adm": 58.0 + 2.0 * (l1 / 1.0e-06),
        "output_swing": 0.86,
        "pm": 63.0 - 0.02 * (w1 / 1.0e-06),
        "rms_noise_out": 6.6e-05 + 0.8 * idc,
        "lg_ugb": 2.2e06,
        "psrr": 61.0 + 0.5 * (l1 / 1.0e-06),
        "slew_rate_rise": 2.15e06,
        "slew_rate_fall": 2.12e06,
    }
    return [float(perfs[name]) for name in _perf_order()]


def _build_multi_simulation_record(path: Path) -> None:
    order = _design_var_order()
    baseline = _baseline_design()
    records = []
    for idx, idc in enumerate([6.0e-06, 5.0e-06, 4.0e-06, 3.0e-06], start=1):
        design = dict(baseline)
        design["Idc"] = idc
        design["l1"] = 1.6e-06
        design["w1"] = 2.5e-05
        records.append(
            {
                "iter": idx,
                "parameters": [float(design[name]) for name in order],
                "performance": _synthetic_performance_vector(design),
            }
        )
    path.write_text(json.dumps(records, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _candidate_payload(idc_value: float, l1_value: float, w1_value: float, rationale: str) -> dict:
    return {
        "updated_design_vars": [
            {"name": "Idc", "value": idc_value, "reason": "adjust bias current"},
            {"name": "l1", "value": l1_value, "reason": "tune output resistance"},
            {"name": "w1", "value": w1_value, "reason": "rebalance gm and current"},
        ],
        "predicted_performances": [],
        "rationale": rationale,
    }


def _candidate_payload_with_predictions(
    idc_value: float,
    l1_value: float,
    w1_value: float,
    rationale: str,
) -> dict:
    candidate = _candidate_payload(idc_value, l1_value, w1_value, rationale)
    candidate["predicted_performances"] = [
        {"name": metric, "value": 1.0 + idx, "reason": "llm predicted absolute value"}
        for idx, metric in enumerate(_metric_names())
    ]
    return candidate


def _valid_worker_payload() -> dict:
    return {
        "role_name": "Bias network",
        "target_metric": "power",
        "candidates": [
            _candidate_payload_with_predictions(4.2e-06, 1.5e-06, 2.7e-05, "favor lower current"),
        ],
        "rationale": "Bias adjustments target power first while preserving other specs.",
    }


class TestIterativeWorker(unittest.TestCase):
    def test_build_worker_context_uses_recent_records_for_improving_examples(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_multi_simulation_record(simulation_record_path)

            context = build_worker_context(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
            )

        self.assertGreater(len(context["improving_design_samples"]["latest"]), 0)
        self.assertGreater(len(context["improving_design_samples"]["best"]), 0)
        self.assertGreater(len(context["latest_results"]), 0)

    def test_build_worker_context_keeps_improving_examples_empty_when_only_one_record_exists(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            context = build_worker_context(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
            )

        self.assertEqual(context["improving_design_samples"]["latest"], [])
        self.assertEqual(context["improving_design_samples"]["best"], [])
        self.assertEqual(len(context["latest_results"]), 1)

    def test_build_worker_context_filters_working_state_and_improving_samples_to_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_multi_simulation_record(simulation_record_path)

            context = build_worker_context(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                simulation_record_path=str(simulation_record_path),
                current_design_vars=_baseline_design(),
                current_predicted_perfs={},
            )

        role_vars = set(context["role_variables"])
        self.assertEqual(set(context["working_state"]["design_vars"].keys()), role_vars)
        self.assertLessEqual(len(context["improving_design_samples"]["latest"]), 5)
        self.assertLessEqual(len(context["improving_design_samples"]["best"]), 5)
        self.assertLessEqual(len(context["latest_results"]), 5)
        for record in context["latest_results"]:
            self.assertIn("iter", record)
            self.assertIn("design_vars", record)
            self.assertIn("performances", record)
            self.assertEqual(set(record["design_vars"].keys()), role_vars)
        self.assertLessEqual(len(context["worker_local_summary"]["role_variable_signals"]), 3)
        for group_name in ("latest", "best"):
            for sample in context["improving_design_samples"][group_name]:
                self.assertIn("iters", sample)
                self.assertIn("var_changes", sample)
                self.assertIn("metric_changes", sample)
                for change in sample["var_changes"]:
                    self.assertIn(change["name"], role_vars)

    def test_worker_allows_partial_role_updates(self) -> None:
        payload = {
            "role_name": "Bias network",
            "target_metric": "power",
            "candidates": [
                {
                    "updated_design_vars": [
                        {
                            "name": "Idc",
                            "value": 4.2e-06,
                            "reason": "adjust only the main bias lever",
                        }
                    ],
                    "predicted_performances": [
                        {"name": metric, "value": 1.0 + idx, "reason": "LLM prediction"}
                        for idx, metric in enumerate(_metric_names())
                    ],
                    "rationale": "Touch only the strongest variable.",
                },
            ],
            "rationale": "Provide focused single-variable moves.",
        }

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            result = run_iterative_worker(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                worker_instruction="Lower power with minimal side effects.",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
                llm_client=_FakeLLMClient([payload]),
            )

        updates = {item["name"] for item in result["updated_design_vars"]}
        self.assertEqual(updates, {"Idc"})
        self.assertEqual(len(result["predicted_performances"]), len(_metric_names()))

    def test_worker_success(self) -> None:
        payload = _valid_worker_payload()

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            result = run_iterative_worker(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                worker_instruction="Lower power with minimal side effects.",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
                llm_client=_FakeLLMClient([payload]),
            )

        self.assertEqual(result["role_name"], "Bias network")
        self.assertEqual(result["target_metric"], "power")
        self.assertEqual(
            {item["name"] for item in result["updated_design_vars"]}, {"l1", "w1", "Idc"}
        )
        self.assertEqual(len(result["predicted_performances"]), len(_metric_names()))

    def test_worker_prompt_includes_critical_heuristics_section(self) -> None:
        payload = _valid_worker_payload()
        fake = _FakeLLMClient([payload])

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            with patch(
                "agentic_sizing.iteration.iterative_worker.retrieve_critical_heuristics",
                return_value=["Increase Idc (not Idc2 or Idc3) can improve slew rates."],
            ):
                run_iterative_worker(
                    case_name="5t_ota",
                    role_name="Bias network",
                    target_metric="power",
                    worker_instruction="Lower power with minimal side effects.",
                    simulation_record_path=str(simulation_record_path),
                    current_design_vars={},
                    current_predicted_perfs={},
                    llm_client=fake,
                )

        prompt = fake.requests[0].messages[1].content
        self.assertIn("Retrieved critical heuristics for this case and target:", prompt)
        self.assertIn("Increase Idc (not Idc2 or Idc3) can improve slew rates.", prompt)

    def test_worker_keeps_llm_predictions(self) -> None:
        payload = {
            "role_name": "Bias network",
            "target_metric": "power",
            "candidates": [
                _candidate_payload_with_predictions(
                    4.2e-06, 1.5e-06, 2.7e-05, "favor lower current"
                ),
            ],
            "rationale": "Bias adjustments target power first while preserving other specs.",
        }

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_multi_simulation_record(simulation_record_path)

            result = run_iterative_worker(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                worker_instruction="Lower power with minimal side effects.",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
                llm_client=_FakeLLMClient([payload]),
            )

        self.assertEqual(len(result["predicted_performances"]), len(_metric_names()))
        self.assertTrue(
            all("llm predicted" in item["reason"] for item in result["predicted_performances"])
        )

    def test_worker_prompt_includes_local_summary(self) -> None:
        payload = _valid_worker_payload()
        fake = _FakeLLMClient([payload])

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            run_iterative_worker(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                worker_instruction="Lower power with minimal side effects.",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
                llm_client=fake,
            )

        prompt = fake.requests[0].messages[1].content
        self.assertIn("Tactical local summary:", prompt)
        self.assertIn('"phase"', prompt)
        self.assertIn('"oscillation_alerts"', prompt)
        self.assertNotIn('"target_metric_status"', prompt)
        self.assertNotIn('"current_unsatisfied_metrics"', prompt)
        self.assertNotIn('"recent_target_metric_trend"', prompt)
        self.assertNotIn('"working_design_snapshot"', prompt)

    def test_worker_prompt_includes_prediction_rules_in_llm_mode(self) -> None:
        payload = {
            "role_name": "Bias network",
            "target_metric": "power",
            "candidates": [
                _candidate_payload_with_predictions(
                    4.2e-06, 1.5e-06, 2.7e-05, "favor lower current"
                ),
            ],
            "rationale": "Bias adjustments target power first while preserving other specs.",
        }
        fake = _FakeLLMClient([payload])

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            run_iterative_worker(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                worker_instruction="Lower power with minimal side effects.",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
                llm_client=fake,
            )

        prompt = fake.requests[0].messages[1].content
        self.assertIn("Predict absolute values for all performance metrics", prompt)
        self.assertIn("Return exactly 1 candidate update", prompt)
        self.assertIn('"predicted_performances"', prompt)
        self.assertIn("Use `oscillation_alerts` and `target_tradeoff_metrics`", prompt)
        self.assertIn(
            "Latest 5 committed results (role-owned vars only; performances are global):", prompt
        )
        self.assertIn("Recent improving examples (best 5, role-owned vars only):", prompt)
        self.assertNotIn("Recent improving examples (latest 5, role-owned vars only):", prompt)
        self.assertIn("Do not reopen a recently recovered spec", prompt)

    def test_worker_stores_latest_prompt_log(self) -> None:
        payload = _valid_worker_payload()

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            run_iterative_worker(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                worker_instruction="Lower power with minimal side effects.",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
                llm_client=_FakeLLMClient([payload]),
            )

            prompt_log_path = (
                simulation_record_path.parent
                / f"{simulation_record_path.stem}_worker_prompt_sample.txt"
            )
            state_path = (
                simulation_record_path.parent
                / f"{simulation_record_path.stem}_worker_prompt_sample.state.json"
            )
            self.assertTrue(prompt_log_path.exists())
            self.assertTrue(state_path.exists())

            prompt_log = prompt_log_path.read_text(encoding="utf-8")
            self.assertIn("role_name: Bias network", prompt_log)
            self.assertIn("target_metric: power", prompt_log)
            self.assertIn("sampling_method: latest_only_overwrite", prompt_log)
            self.assertIn("seen_worker_calls: 1", prompt_log)
            self.assertIn("Role substructures:", prompt_log)
            self.assertNotIn('"evidence":', prompt_log)
            self.assertNotIn('"base_type":', prompt_log)
            self.assertNotIn('"modifiers":', prompt_log)
            self.assertNotIn('"calc_expr":', prompt_log)
            self.assertNotIn('"weight":', prompt_log)
            self.assertNotIn("n=", prompt_log)
            self.assertNotIn("tends to improve", prompt_log)
            self.assertNotIn("tends to degrade", prompt_log)

    def test_worker_prompt_log_overwrites_with_latest_prompt(self) -> None:
        first_payload = _valid_worker_payload()
        second_payload = _valid_worker_payload()

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            run_iterative_worker(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                worker_instruction="First worker instruction.",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
                llm_client=_FakeLLMClient([first_payload]),
            )

            run_iterative_worker(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                worker_instruction="Second worker instruction.",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
                llm_client=_FakeLLMClient([second_payload]),
            )

            prompt_log_path = (
                simulation_record_path.parent
                / f"{simulation_record_path.stem}_worker_prompt_sample.txt"
            )
            state_path = (
                simulation_record_path.parent
                / f"{simulation_record_path.stem}_worker_prompt_sample.state.json"
            )
            prompt_log = prompt_log_path.read_text(encoding="utf-8")
            state = json.loads(state_path.read_text(encoding="utf-8"))

            self.assertIn("sampling_method: latest_only_overwrite", prompt_log)
            self.assertIn("seen_worker_calls: 2", prompt_log)
            self.assertNotIn("First worker instruction.", prompt_log)
            self.assertIn("Second worker instruction.", prompt_log)
            self.assertEqual(state["seen_worker_calls"], 2)
            self.assertEqual(state["logged_prompt_count"], 1)

    def test_worker_retries_on_out_of_range_value(self) -> None:
        invalid = _valid_worker_payload()
        for item in invalid["candidates"][0]["updated_design_vars"]:
            if item["name"] == "Idc":
                item["value"] = 1.0

        valid = _valid_worker_payload()
        fake = _FakeLLMClient([invalid, valid])

        with tempfile.TemporaryDirectory() as td:
            simulation_record_path = Path(td) / "simulation_record.json"
            _build_simulation_record(simulation_record_path)

            result = run_iterative_worker(
                case_name="5t_ota",
                role_name="Bias network",
                target_metric="power",
                worker_instruction="Lower power with minimal side effects.",
                simulation_record_path=str(simulation_record_path),
                current_design_vars={},
                current_predicted_perfs={},
                max_retries=1,
                llm_client=fake,
            )

        self.assertEqual(fake.calls, 2)
        self.assertEqual(result["role_name"], "Bias network")


if __name__ == "__main__":
    unittest.main()
