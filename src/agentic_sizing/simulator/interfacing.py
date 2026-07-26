from __future__ import annotations

import csv
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

Settings = Mapping[str, Any]
PathLike = str | os.PathLike[str]


def _coerce_values_matrix(settings: Settings, values: Any) -> np.ndarray:
    """Normalize design-variable values to a [N, D] float matrix."""
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2:
        raise ValueError("values must be a 1D/2D numeric array")

    expected_dim = len(settings["des_vars"])
    if matrix.shape[1] != expected_dim:
        raise ValueError(
            f"values dimension mismatch: got D={matrix.shape[1]}, expected D={expected_dim}"
        )
    return matrix


def _objective_violation(
    performances: np.ndarray, settings: Settings
) -> tuple[np.ndarray, np.ndarray]:
    if performances.ndim != 2:
        raise ValueError("performances must have shape [candidates, metrics]")

    objectives = performances[:, 0]
    violation_array = np.zeros_like(performances)
    for i, (_, (threshold, method, weight, _)) in enumerate(settings["outputs"].items()):
        if method == "min":
            violation_array[:, i] = np.clip(threshold - performances[:, i], 0, None) * weight
        elif method == "max":
            violation_array[:, i] = np.clip(performances[:, i] - threshold, 0, None) * weight
    violations = np.sum(violation_array, axis=1)
    return objectives, violations


def _get_violation_ranking(
    performances: np.ndarray, settings: Settings
) -> tuple[int, int, np.ndarray]:
    objectives, violations = _objective_violation(performances, settings)
    validations = objectives + violations
    rank_indices = np.argsort(np.argsort(validations))
    return int(np.argmin(rank_indices)), int(np.argmax(rank_indices)), rank_indices


def _workspace_root() -> Path:
    configured = os.getenv("AGENTIC_SIZING_CADENCE_WORK_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / "output" / "cadence_workspaces").resolve()


def _copy_simulation_workspace(project_dir: PathLike, workspace: Path) -> None:
    project_path = Path(project_dir).expanduser().resolve()
    if not project_path.is_dir():
        raise FileNotFoundError(f"Cadence project directory not found: {project_path}")

    cds_lib_path = project_path / "cds.lib"
    if not cds_lib_path.is_file():
        raise FileNotFoundError(f"Cadence project is missing cds.lib: {cds_lib_path}")

    workspace.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cds_lib_path, workspace / "cds.lib")

    for line in cds_lib_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("DEFINE "):
            continue
        parts = stripped.split(maxsplit=2)
        if len(parts) != 3:
            continue
        _, lib_name, lib_path = parts
        if lib_name != lib_path:
            continue
        source = project_path / lib_path
        if not source.exists():
            continue
        target = workspace / source.name
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def _prepare_simulation_workspace(settings: Settings) -> Path:
    project_dir = settings["ocn_script"]["assembler"][0]
    library, cell, view = settings["ocn_script"]["assembler"][-3:]
    workspace_parent = _workspace_root() / f"{library}_{cell}_{view}"
    workspace_parent.mkdir(parents=True, exist_ok=True)

    workspace = Path(tempfile.mkdtemp(prefix="Sim_", dir=workspace_parent))
    _copy_simulation_workspace(project_dir, workspace)
    return workspace


def update_skill(
    settings: Settings,
    values: Any,
    skill_file_path: PathLike,
    output_file_path: PathLike,
) -> None:
    values = _coerce_values_matrix(settings, values)

    library, cell, view = settings["ocn_script"]["assembler"][-3:]

    lines = [f'maeOpenSetup("{library}" "{cell}" "{view}")']
    for index, (var_name, var_range) in enumerate(settings["des_vars"].items()):
        _, _, is_int = var_range
        column = np.asarray(values[:, index], dtype=int) if is_int else values[:, index]
        lines.append(f'maeSetVar("{var_name}" "{" ".join(map(str, column))}")')

    lines.extend(
        [
            "maeRunSimulation()",
            "maeWaitUntilDone('All)",
            f'maeExportOutputView(?fileName "{output_file_path}")',
            "exit()",
        ]
    )
    Path(skill_file_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_simulation(skill_script_path: PathLike, cwd: PathLike) -> tuple[int, float]:
    started_at = time.perf_counter()
    completed = subprocess.run(
        ["virtuoso", "-nograph", "-restore", str(skill_script_path)],
        cwd=cwd,
        check=False,
    )
    return completed.returncode, time.perf_counter() - started_at


def _fallback_output_value(method: str, threshold: float, objective_mode: str) -> float:
    if method == "max":
        return threshold + 1e3 * threshold
    if method == "min":
        return threshold - 1e3 * threshold
    if method == "target":
        return 1 if objective_mode == "min" else 0
    raise ValueError("method should be in ['max', 'min', 'target']")


def read_response(
    settings: Settings, result_file_path: PathLike, wait_timeout_s: float = 120.0
) -> dict[str, list[float]]:
    result_path = Path(result_file_path)
    deadline = time.monotonic() + wait_timeout_s
    while not result_path.exists():
        if time.monotonic() > deadline:
            raise TimeoutError(f"Simulation result not found: {result_path}")
        time.sleep(0.1)

    data: dict[str, list[float]] = {}

    with result_path.open("r", encoding="utf-8", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        if not reader.fieldnames:
            raise ValueError(f"Invalid result CSV without headers: {result_path}")

        response_fieldname = "Parameter"
        response_value_fieldname = sorted(
            [field for field in reader.fieldnames if "Nominal" in field]
        )

        if response_fieldname not in reader.fieldnames:
            raise ValueError(f"Missing 'Parameter' column in result CSV: {result_path}")
        if not response_value_fieldname:
            raise ValueError(f"Missing Nominal columns in result CSV: {result_path}")

        outputs = settings["outputs"]
        objective_mode = settings["objective"]["minormax"]

        for row in reader:
            response_name = row.get(response_fieldname)
            if response_name not in outputs:
                continue

            threshold, method, _, _ = outputs[response_name]
            values = data.setdefault(response_name, [])
            for value_name in response_value_fieldname:
                value_str = row.get(value_name, "")
                try:
                    value = float(value_str)
                except (TypeError, ValueError):
                    value = _fallback_output_value(method, threshold, objective_mode)
                values.append(value)

    return data


def calc_outputs(
    value_nums: int, responses: Mapping[str, Sequence[float]], settings: Settings
) -> np.ndarray:
    output_names = list(settings["outputs"].keys())
    missing = [name for name in output_names if name not in responses]
    if missing:
        raise ValueError(f"Missing outputs in simulation result: {missing}")

    output = [responses[name] for name in output_names]
    output = np.nan_to_num(np.array(output), nan=0.0).transpose(1, 0)
    output = output.reshape(value_nums, -1, output.shape[-1])

    if output.shape[1] == 1:
        return output[:, 0]

    # Choose the worst corner for each candidate.
    worst_corners = np.zeros((value_nums, output.shape[-1]))
    for i in range(value_nums):
        _, worst_idx, _ = _get_violation_ranking(output[i], settings)
        worst_corners[i] = output[i, worst_idx]

    return worst_corners


def assembler(
    settings: Settings,
    values: Any,
    skill_file_path: PathLike = "simulation_skill.il",
    result_file_path: PathLike = "simResults.csv",
    max_retries: int = 2,
) -> tuple[np.ndarray, float]:
    """Run one simulation task and export performance matrix."""
    values = _coerce_values_matrix(settings, values)
    workspace = _prepare_simulation_workspace(settings)
    requested_skill_path = Path(skill_file_path).expanduser()
    requested_result_path = Path(result_file_path).expanduser()
    workspace_skill_path = workspace / requested_skill_path.name
    workspace_result_path = workspace / requested_result_path.name

    flag_mc = settings["ocn_script"]["assembler"][2]
    if flag_mc:
        raise NotImplementedError("Monte Carlo flow is not included in simulator minimal chain.")

    update_skill(settings, values, str(workspace_skill_path), str(workspace_result_path))
    if workspace_skill_path.resolve() != requested_skill_path.resolve():
        requested_skill_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workspace_skill_path, requested_skill_path)

    last_error: Exception = RuntimeError("simulation did not start")
    for _ in range(max_retries + 1):
        workspace_result_path.unlink(missing_ok=True)
        requested_result_path.unlink(missing_ok=True)

        simulation_status, cost_time = run_simulation(
            str(workspace_skill_path),
            cwd=str(workspace),
        )
        if simulation_status != 0:
            last_error = RuntimeError(f"Cadence simulation failed with status={simulation_status}")
            continue

        try:
            responses = read_response(settings, str(workspace_result_path))
            performance = calc_outputs(values.shape[0], responses, settings)
            if workspace_result_path.resolve() != requested_result_path.resolve():
                requested_result_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(workspace_result_path, requested_result_path)
            return performance, cost_time
        except Exception as exc:  # local validation/read failure, retry
            last_error = exc

    raise RuntimeError(f"Cadence simulation failed after retries: {last_error}")
