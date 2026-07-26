from __future__ import annotations

import csv
import os
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path

import numpy as np


def _coerce_values_matrix(settings, values):
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


def _objective_violation(performances, settings):
    assert len(performances.shape) == 2, "performances should be (N, dims)."

    objectives = performances[:, 0]
    violation_array = np.zeros_like(performances)
    for i, (_, (threshold, method, weight, _)) in enumerate(settings["outputs"].items()):
        if method == "min":
            violation_array[:, i] = np.clip(threshold - performances[:, i], 0, None) * weight
        elif method == "max":
            violation_array[:, i] = np.clip(performances[:, i] - threshold, 0, None) * weight
    violations = np.sum(violation_array, axis=1)
    return objectives, violations


def _get_violation_ranking(performances, settings):
    objectives, violations = _objective_violation(performances, settings)
    validations = objectives + violations
    rank_indices = np.argsort(np.argsort(validations))
    best_idx = np.argmin(rank_indices)
    worst_idx = np.argmax(rank_indices)
    return best_idx, worst_idx, rank_indices


def _workspace_root() -> Path:
    configured = os.getenv("AGENTIC_SIZING_CADENCE_WORK_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / "output" / "cadence_workspaces").resolve()


def _copy_simulation_workspace(project_dir: str | os.PathLike[str], workspace: Path) -> None:
    project_path = Path(project_dir).expanduser().resolve()
    cds_lib_path = project_path / "cds.lib"
    if not cds_lib_path.exists():
        return

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


def _prepare_simulation_workspace(settings) -> Path:
    project_dir = settings["ocn_script"]["assembler"][0]
    library, cell, view = settings["ocn_script"]["assembler"][-3:]
    workspace_parent = _workspace_root() / f"{library}_{cell}_{view}"
    workspace_parent.mkdir(parents=True, exist_ok=True)

    workspace = workspace_parent / f"Sim_{os.getpid()}_{int(time.time() * 1000)}"
    _copy_simulation_workspace(project_dir, workspace)
    return workspace


def _write_skill(settings, values, skill_file_path, output_file_path, flag_cn=False):
    values = _coerce_values_matrix(settings, values)

    library, cell, view = settings["ocn_script"]["assembler"][-3:]
    if flag_cn:
        view = f"{view}_cn"

    with open(skill_file_path, "w", encoding="utf-8") as file:
        file.write('maeOpenSetup("{}" "{}" "{}")\n'.format(library, cell, view))

        for i, (var_name, var_range) in enumerate(settings["des_vars"].items()):
            _, _, is_int = var_range
            var_value = np.array(values[:, i], dtype=int) if is_int else values[:, i]
            var_value = [str(value) for value in var_value]
            file.write('maeSetVar("{}" "{}")\n'.format(var_name, " ".join(var_value)))

        file.write("maeRunSimulation()\n")
        file.write("maeWaitUntilDone('All)\n")
        if flag_cn:
            file.write(f'maeExportOutputView(?fileName "{output_file_path}" ?view "Detail")\n')
        else:
            file.write(f'maeExportOutputView(?fileName "{output_file_path}")\n')

        # if not parallel:
        file.write("exit()\n")

    return 0


def update_skill(settings, values, skill_file_path, output_file_path):
    return _write_skill(settings, values, skill_file_path, output_file_path, flag_cn=False)


def update_skill_cn(settings, values, skill_file_path, output_file_path):
    return _write_skill(settings, values, skill_file_path, output_file_path, flag_cn=True)


def update_skill_mc(settings, values, skill_file_path, output_file_path):
    raise NotImplementedError("Monte Carlo flow is not included in simulator minimal chain.")


def run_simulation(skill_script_path, log_path=None, cwd=None):
    start_time = time.time()

    cmd = ["virtuoso", "-nograph", "-restore", skill_script_path]
    if log_path:
        with open(log_path, "w", encoding="utf-8") as f:
            status = subprocess.call(cmd, stdout=f, stderr=f, cwd=cwd)
    else:
        status = subprocess.call(cmd, cwd=cwd)

    cost_time = time.time() - start_time
    return status, cost_time


def _fallback_output_value(method, threshold, objective_mode):
    if method == "max":
        return threshold + 1e3 * threshold
    if method == "min":
        return threshold - 1e3 * threshold
    if method == "target":
        return 1 if objective_mode == "min" else 0
    raise ValueError("method should be in ['max', 'min', 'target']")


def read_response(settings, result_file_path, wait_timeout_s=120.0):
    deadline = time.time() + wait_timeout_s
    while not os.path.exists(result_file_path):
        if time.time() > deadline:
            raise TimeoutError(f"Simulation result not found: {result_file_path}")
        time.sleep(0.1)

    data = defaultdict(list)

    with open(result_file_path, "r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        if not reader.fieldnames:
            raise ValueError(f"Invalid result CSV without headers: {result_file_path}")

        response_fieldname = "Parameter"
        response_value_fieldname = sorted(
            [field for field in reader.fieldnames if "Nominal" in field]
        )

        if response_fieldname not in reader.fieldnames:
            raise ValueError(f"Missing 'Parameter' column in result CSV: {result_file_path}")
        if not response_value_fieldname:
            raise ValueError(f"Missing Nominal columns in result CSV: {result_file_path}")

        outputs = settings["outputs"]
        objective_mode = settings["objective"]["minormax"]

        for row in reader:
            response_name = row.get(response_fieldname)
            if response_name not in outputs:
                continue

            threshold, method, _, _ = outputs[response_name]
            for value_name in response_value_fieldname:
                value_str = row.get(value_name, "")
                try:
                    value = float(value_str)
                except (TypeError, ValueError):
                    value = _fallback_output_value(method, threshold, objective_mode)
                data[response_name].append(value)

    return data


def read_response_mc(settings, result_file_path):
    raise NotImplementedError("Monte Carlo flow is not included in simulator minimal chain.")


def calc_outputs(value_nums, responses, settings):
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
    flag_cn,
    settings,
    values,
    skill_file_path="TRY2.txt",
    result_file_path="simResults.csv",
    sim_log_path=None,
    max_retries=2,
):
    """Run one simulation task and export performance matrix."""
    values = _coerce_values_matrix(settings, values)
    workspace = _prepare_simulation_workspace(settings)
    requested_skill_path = Path(skill_file_path).expanduser()
    requested_result_path = Path(result_file_path).expanduser()
    workspace_skill_path = workspace / requested_skill_path.name
    workspace_result_path = workspace / requested_result_path.name
    requested_log_path = Path(sim_log_path).expanduser() if sim_log_path else None
    workspace_log_path = workspace / requested_log_path.name if requested_log_path else None

    flag_mc = settings["ocn_script"]["assembler"][2]
    if flag_mc:
        raise NotImplementedError("Monte Carlo flow is not included in simulator minimal chain.")

    updater = update_skill_cn if flag_cn else update_skill
    update_status = updater(settings, values, str(workspace_skill_path), str(workspace_result_path))
    if update_status != 0:
        raise RuntimeError("Update skill failed")
    if workspace_skill_path.resolve() != requested_skill_path.resolve():
        requested_skill_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workspace_skill_path, requested_skill_path)

    last_error = None
    for _ in range(max_retries + 1):
        if workspace_result_path.exists():
            workspace_result_path.unlink()
        if requested_result_path.exists():
            requested_result_path.unlink()

        simulation_status, cost_time = run_simulation(
            str(workspace_skill_path),
            str(workspace_log_path) if workspace_log_path else None,
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
            if workspace_log_path and requested_log_path and workspace_log_path.exists():
                requested_log_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(workspace_log_path, requested_log_path)
            return performance, cost_time
        except Exception as exc:  # local validation/read failure, retry
            last_error = exc

    raise RuntimeError(f"Cadence simulation failed after retries: {last_error}")


def _iter_batch_values(settings, batch_values):
    arr = np.asarray(batch_values, dtype=float)
    if arr.ndim == 2:
        yield _coerce_values_matrix(settings, arr)
        return
    if arr.ndim == 3:
        for values in arr:
            yield _coerce_values_matrix(settings, values)
        return
    raise ValueError("batch_values must be shape [N,D] or [B,N,D]")


def batch_assembler(flag_cn, settings, batch_values):
    performances, cost_times = [], []
    for idx, values in enumerate(_iter_batch_values(settings, batch_values)):
        performance, cost_time = assembler(
            flag_cn,
            settings,
            values,
            skill_file_path=f"Sim{idx}_skill.txt",
            result_file_path=f"Sim{idx}_result.csv",
        )
        performances.append(performance)
        cost_times.append(cost_time)

    return np.stack(performances, axis=0), np.array(cost_times)


class CadenceInterface:
    """Minimal simulation interface: design variables in, performances out."""

    def __init__(self, logger, settings, working_dir):
        self.logger = logger
        self.settings = settings
        self.working_dir = working_dir
        os.path.exists(working_dir) or os.makedirs(working_dir)
        self.simulation_tasks = []

    def load(self, state):
        self.simulation_tasks = list(state.get("tasks", []))

    def batch_assembler(self, flag_cn, batch_values):
        task_idx = len(self.simulation_tasks)
        skill_file_path = os.path.join(self.working_dir, f"Sim{task_idx}_skill.txt")
        result_file_path = os.path.join(self.working_dir, f"Sim{task_idx}_result.csv")

        performances, cost_time = assembler(
            flag_cn=flag_cn,
            settings=self.settings,
            values=batch_values,
            skill_file_path=skill_file_path,
            result_file_path=result_file_path,
        )

        self.simulation_tasks.append(
            {
                "task_idx": task_idx,
                "skill_file_path": skill_file_path,
                "result_file_path": result_file_path,
                "cost_time": cost_time,
            }
        )
        return performances, cost_time

    def adjust_pool(self, worker_num):
        # Kept for compatibility with old call sites.
        if self.logger:
            self.logger.info("CadenceInterface is in single-run mode; adjust_pool is a no-op.")

    def output_result(self, result_dir, values, flag_cn):
        os.path.exists(result_dir) or os.makedirs(result_dir)
        skill_file_path = os.path.join(result_dir, "Result_skill.txt")
        result_file_path = os.path.join(result_dir, "Result_result.csv")
        return assembler(flag_cn, self.settings, values, skill_file_path, result_file_path)


if __name__ == "__main__":
    from utils import parse_yaml

    yaml_path = "yaml_settings/2024_comparator_shared.yaml"
    settings = parse_yaml(yaml_path)

    # Example shape: [N, D]. Replace with real design variables before running.
    values = np.zeros((1, len(settings["des_vars"])))
    perf, cost = assembler(False, settings, values)
    print(perf, cost)
