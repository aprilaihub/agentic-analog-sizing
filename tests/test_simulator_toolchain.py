from __future__ import annotations

import csv
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - environment guard
    np = None  # type: ignore[assignment]

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
try:
    interfacing = importlib.import_module("agentic_sizing.simulator.interfacing")
    utils = importlib.import_module("agentic_sizing.simulator.utils")
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    if exc.name == "numpy":
        interfacing = None  # type: ignore[assignment]
        utils = None  # type: ignore[assignment]
    else:
        raise


@unittest.skipIf(interfacing is None or utils is None, "simulator dependencies are not installed")
class TestSimulatorToolchain(unittest.TestCase):
    def test_imports(self) -> None:
        self.assertTrue(hasattr(interfacing, "assembler"))
        self.assertTrue(hasattr(utils, "parse_yaml"))

    def test_parse_yaml_normalization(self) -> None:
        yaml_text = """
ocn_script:
  assembler: ["/tmp/project", 0, 0, 0, "lib", "cell", "view"]
des_vars:
  x: [0, 10]
  y: [0.0, 1.5, 0]
  z: [1, 9, 1]
dependent_vars: null
responses:
  assembler: [power, cmrr]
outputs:
  power: [4e-6, target, 1, "*value"]
  cmrr: [80, min, 0.00125, "*value"]
options:
  corner_opt: 0
  parallel: 0
  parallel_max: 1
objective:
  name: power
  minormax: min
constraints: null
intentions: null
"""
        with tempfile.TemporaryDirectory() as td:
            settings_path = Path(td) / "settings.yaml"
            settings_path.write_text(yaml_text, encoding="utf-8")

            parsed = utils.parse_yaml(str(settings_path))

        self.assertEqual(parsed["des_vars"]["x"], [0.0, 10.0, 0])
        self.assertEqual(parsed["des_vars"]["z"], [1, 9, 1])
        self.assertEqual(parsed["outputs"]["power"], [4e-06, "target", 1.0, "*value"])
        self.assertEqual(parsed["dependent_vars"], [])
        self.assertEqual(parsed["intentions"], [])

    def test_parse_yaml_expands_cadence_project_dir(self) -> None:
        yaml_text = """
ocn_script:
  assembler: ["${CADENCE_PROJECT_DIR}", 0, 0, 0, "lib", "cell", "view"]
des_vars:
  x: [0, 1]
outputs:
  power: [1, max, 1, "*value"]
"""
        with tempfile.TemporaryDirectory() as td:
            settings_path = Path(td) / "settings.yaml"
            settings_path.write_text(yaml_text, encoding="utf-8")
            with patch.dict(os.environ, {"CADENCE_PROJECT_DIR": "/cadence/project"}):
                parsed = utils.parse_yaml(str(settings_path))

        self.assertEqual(parsed["ocn_script"]["assembler"][0], "/cadence/project")

    def test_update_skill_generates_expected_skill_script(self) -> None:
        if np is None:
            self.skipTest("numpy not installed")

        settings = {
            "ocn_script": {"assembler": ["/tmp/project", 0, 0, 0, "lib", "cell", "view"]},
            "options": {"parallel": 0},
            "des_vars": {
                "x": [0, 10, 1],
                "y": [0.0, 1.0, 0],
            },
        }
        values = np.array(
            [
                [1.2, 0.10],
                [2.8, 0.25],
            ],
            dtype=float,
        )

        with tempfile.TemporaryDirectory() as td:
            skill_path = Path(td) / "sim_skill.il"
            result_path = Path(td) / "sim_result.csv"
            interfacing.update_skill(settings, values, str(skill_path), str(result_path))
            content = skill_path.read_text(encoding="utf-8")

        self.assertIn('maeOpenSetup("lib" "cell" "view")', content)
        self.assertIn('maeSetVar("x" "1 2")', content)
        self.assertIn('maeSetVar("y" "0.1 0.25")', content)
        self.assertIn("maeRunSimulation()", content)
        self.assertIn("maeWaitUntilDone('All)", content)

    def test_read_response_extracts_nominal_values(self) -> None:
        settings = {
            "outputs": {
                "power": [4e-6, "target", 1.0, "*value"],
                "cmrr": [80.0, "min", 0.00125, "*value"],
            },
            "objective": {"name": "power", "minormax": "min"},
        }

        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "result.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["Parameter", "Nominal1", "Nominal2"])
                writer.writeheader()
                writer.writerow(
                    {"Parameter": "power", "Nominal1": "1.2e-05", "Nominal2": "9.9e-06"}
                )
                writer.writerow({"Parameter": "cmrr", "Nominal1": "79.1", "Nominal2": "81.5"})
                writer.writerow({"Parameter": "unused_metric", "Nominal1": "0", "Nominal2": "0"})

            data = interfacing.read_response(settings, str(csv_path))

        self.assertEqual(data["power"], [1.2e-05, 9.9e-06])
        self.assertEqual(data["cmrr"], [79.1, 81.5])
        self.assertNotIn("unused_metric", data)

    def test_prepare_simulation_workspace_copies_cds_lib(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            (project_dir / "cds.lib").write_text(
                "DEFINE local_lib local_lib\n",
                encoding="utf-8",
            )
            (project_dir / "local_lib").mkdir()
            (project_dir / "local_lib" / "marker.txt").write_text("ok\n", encoding="utf-8")

            settings = {
                "ocn_script": {"assembler": [str(project_dir), 0, 0, 0, "lib", "cell", "view"]},
            }

            workspace_root = Path(td) / "workspaces"
            with patch.dict(os.environ, {"AGENTIC_SIZING_CADENCE_WORK_ROOT": str(workspace_root)}):
                workspace = Path(interfacing._prepare_simulation_workspace(settings))

            self.assertTrue((workspace / "cds.lib").exists())
            self.assertTrue((workspace / "local_lib" / "marker.txt").exists())

    def test_prepare_simulation_workspace_requires_cds_lib(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            settings = {
                "ocn_script": {"assembler": [str(project_dir), 0, 0, 0, "lib", "cell", "view"]},
            }
            with (
                patch.dict(
                    os.environ,
                    {"AGENTIC_SIZING_CADENCE_WORK_ROOT": str(Path(td) / "workspaces")},
                ),
                self.assertRaisesRegex(FileNotFoundError, "missing cds.lib"),
            ):
                interfacing._prepare_simulation_workspace(settings)

    def test_assembler_runs_virtuoso_from_isolated_workspace(self) -> None:
        if np is None:
            self.skipTest("numpy not installed")

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            (project_dir / "cds.lib").write_text("", encoding="utf-8")
            requested_skill_path = Path(td) / "TRY2.txt"
            requested_result_path = Path(td) / "simResults.csv"

            settings = {
                "ocn_script": {"assembler": [str(project_dir), 0, 0, 0, "lib", "cell", "view"]},
                "options": {"parallel": 0},
                "des_vars": {"x": [0.0, 1.0, 0]},
                "outputs": {"power": [1.0, "target", 1.0, "*value"]},
                "objective": {"name": "power", "minormax": "min"},
            }
            values = np.array([[0.5]], dtype=float)

            def fake_run(skill_script_path, cwd=None):  # type: ignore[no-untyped-def]
                result_path = Path(cwd) / "simResults.csv"
                with result_path.open("w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=["Parameter", "Nominal1"])
                    writer.writeheader()
                    writer.writerow({"Parameter": "power", "Nominal1": "1.0"})
                return 0, 0.01

            with (
                patch.dict(
                    os.environ,
                    {"AGENTIC_SIZING_CADENCE_WORK_ROOT": str(Path(td) / "workspaces")},
                ),
                patch.object(interfacing, "run_simulation", side_effect=fake_run) as mock_run,
            ):
                perf, cost = interfacing.assembler(
                    settings,
                    values,
                    str(requested_skill_path),
                    str(requested_result_path),
                )
                self.assertTrue(requested_skill_path.exists())
                self.assertTrue(requested_result_path.exists())
                self.assertIsNotNone(mock_run.call_args.kwargs["cwd"])

        self.assertEqual(perf.tolist() if hasattr(perf, "tolist") else perf, [[1.0]])
        self.assertEqual(cost, 0.01)


if __name__ == "__main__":
    unittest.main()
