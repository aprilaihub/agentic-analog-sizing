from __future__ import annotations

import random
from typing import Any, Dict, List, Literal, Mapping, Sequence, Tuple

from ..core.operation_region import (
    build_operation_region_summary_from_metric_map,
)
from ..workflow.state import PROJECT_ROOT
from .errors import InitializePipelineError
from .support import _load_json_file, _require_existing_file, _resolve_path

SYNTHETIC_CONTROL_ROLE = "Testbench and bias controls"


def simulate_performance_vector(
    settings_path: str,
    parameters: Sequence[float],
    perf_order: Sequence[str],
    simulation_backend: Literal["real", "mock"] = "real",
) -> Tuple[List[float], float]:
    perf_values, _, elapsed = simulate_performance_vector_with_regions(
        settings_path=settings_path,
        parameters=parameters,
        perf_order=perf_order,
        simulation_backend=simulation_backend,
    )
    return perf_values, elapsed


def simulate_performance_vector_with_regions(
    settings_path: str,
    parameters: Sequence[float],
    perf_order: Sequence[str],
    simulation_backend: Literal["real", "mock"] = "real",
) -> Tuple[List[float], Dict[str, Any], float]:
    import time

    settings_file = _require_existing_file(_resolve_path(settings_path), "settings")
    settings_json = _load_json_file(settings_file, "settings")

    if simulation_backend == "mock":
        start_time = time.perf_counter()
        perf_values = _simulate_mock(settings_json, list(parameters), list(perf_order))
        return (
            perf_values,
            _empty_operation_region_summary(),
            float(time.perf_counter() - start_time),
        )

    return _simulate_real(str(settings_file), list(parameters), list(perf_order))


def simulate_performance_batch_vectors(
    settings_path: str,
    parameter_batch: Sequence[Sequence[float]],
    perf_order: Sequence[str],
    simulation_backend: Literal["real", "mock"] = "real",
) -> Tuple[List[List[float]], List[float]]:
    perf_batch, _, cost_times = simulate_performance_batch_vectors_with_regions(
        settings_path=settings_path,
        parameter_batch=parameter_batch,
        perf_order=perf_order,
        simulation_backend=simulation_backend,
    )
    return perf_batch, cost_times


def simulate_performance_batch_vectors_with_regions(
    settings_path: str,
    parameter_batch: Sequence[Sequence[float]],
    perf_order: Sequence[str],
    simulation_backend: Literal["real", "mock"] = "real",
) -> Tuple[List[List[float]], List[Dict[str, Any]], List[float]]:
    import time

    settings_file = _require_existing_file(_resolve_path(settings_path), "settings")
    settings_json = _load_json_file(settings_file, "settings")
    batch = [[float(value) for value in parameters] for parameters in parameter_batch]
    if not batch:
        raise InitializePipelineError("parameter_batch must contain at least one candidate")

    if simulation_backend == "mock":
        start_time = time.perf_counter()
        perf_batch = [
            _simulate_mock(settings_json, parameters, list(perf_order)) for parameters in batch
        ]
        elapsed = float(time.perf_counter() - start_time)
        per_candidate = elapsed / float(len(batch))
        return (
            perf_batch,
            [_empty_operation_region_summary() for _ in batch],
            [per_candidate for _ in batch],
        )

    (perf_batch, operation_region_summaries), cost_times = _simulate_real_batch(
        str(settings_file),
        batch,
        list(perf_order),
    )
    return perf_batch, operation_region_summaries, cost_times


def _simulate_real(
    settings_path: str,
    parameters: List[float],
    perf_order: List[str],
) -> Tuple[List[float], Dict[str, Any], float]:
    perf_batch, cost_times = _simulate_real_batch(settings_path, [parameters], perf_order)
    perf_values, operation_region_summaries = perf_batch
    return perf_values[0], operation_region_summaries[0], cost_times[0]


def _simulate_real_batch(
    settings_path: str,
    parameter_batch: List[List[float]],
    perf_order: List[str],
) -> Tuple[Tuple[List[List[float]], List[Dict[str, Any]]], List[float]]:
    import numpy as np

    from ..simulator.interfacing import assembler
    from ..simulator.utils import parse_yaml

    settings = parse_yaml(settings_path)
    values = np.asarray(parameter_batch, dtype=float)

    simulator_dir = PROJECT_ROOT / "output" / "cadence_runtime"
    perf_matrix, cost_time_s = assembler(
        settings=settings,
        values=values,
        skill_file_path=str(simulator_dir / "simulation_skill.il"),
        result_file_path=str(simulator_dir / "simResults.csv"),
        # sim_log_path=str(cwd / "init_sim.log"),
    )

    all_output_order = [
        name
        for name in settings.get("outputs", {}).keys()
        if isinstance(name, str) and name.strip()
    ]
    perf_array = np.asarray(perf_matrix, dtype=float)
    if perf_array.shape != (len(parameter_batch), len(all_output_order)):
        raise InitializePipelineError(
            "simulation output dimension mismatch. "
            f"got {perf_array.shape} vs expected {(len(parameter_batch), len(all_output_order))}"
        )
    perf_indices = [all_output_order.index(name) for name in perf_order]
    selected_perf_array = perf_array[:, perf_indices]
    operation_region_summaries = [
        _build_operation_region_summary_from_row(all_output_order, row) for row in perf_array
    ]
    per_candidate_cost = float(cost_time_s) / float(max(len(parameter_batch), 1))
    return (
        selected_perf_array.tolist(),
        operation_region_summaries,
    ), [per_candidate_cost for _ in parameter_batch]


def _build_operation_region_summary_from_row(
    output_order: Sequence[str],
    row: Sequence[float],
) -> Dict[str, Any]:
    metric_map = {
        str(name): float(row[idx]) for idx, name in enumerate(output_order) if idx < len(row)
    }
    return build_operation_region_summary_from_metric_map(metric_map)


def _empty_operation_region_summary() -> Dict[str, Any]:
    return {
        "raw_region_code_note": "No operation-region summary is available for this simulation backend.",
        "available_device_count": 0,
        "available_gm_device_count": 0,
        "region_code_histogram": {},
        "device_regions": {},
        "device_gms": {},
    }


def _simulate_mock(
    settings_json: Mapping[str, Any], parameters: List[float], perf_order: List[str]
) -> List[float]:
    outputs = settings_json.get("outputs")
    if not isinstance(outputs, dict):
        raise InitializePipelineError("settings.outputs must be a JSON object")

    seed = (
        int(sum(abs(value) * (idx + 1) * 1e9 for idx, value in enumerate(parameters))) % 10_000_019
    )

    values: List[float] = []
    for idx, metric in enumerate(perf_order):
        if metric not in outputs:
            raise InitializePipelineError(f"settings.outputs missing metric '{metric}'")
        spec = outputs[metric]
        if not isinstance(spec, list) or len(spec) < 2:
            raise InitializePipelineError(f"settings.outputs.{metric} must have at least 2 items")

        threshold = float(spec[0])
        method = spec[1]
        if not isinstance(method, str):
            raise InitializePipelineError(f"settings.outputs.{metric}[1] must be a string")

        rng = random.Random(seed + idx * 7919)
        jitter = 0.04 + 0.06 * rng.random()

        if method == "min":
            value = threshold * (1.0 + jitter)
        elif method == "max":
            value = threshold * (1.0 - jitter)
        elif method == "target":
            value = threshold * (1.0 + (rng.random() - 0.5) * 0.08)
        else:
            raise InitializePipelineError(
                f"Unsupported output method for mock simulation: {method}"
            )

        values.append(float(value))

    return values
