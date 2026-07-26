import os
from typing import Any, Dict, List, Tuple

import numpy as np
import yaml


def parse_yaml(yaml_path):
    with open(yaml_path, "r", encoding="utf-8") as stream:
        settings = yaml.load(os.path.expandvars(stream.read()), Loader=yaml.FullLoader)
    settings = settings or {}

    # Process des_vars settings
    for var_name, value_range in settings["des_vars"].items():
        is_int = 0
        if len(value_range) == 2:
            value_min, value_max = value_range
        elif len(value_range) == 3:
            value_min, value_max, is_int = value_range
        value_min = int(value_min) if is_int else float(value_min)
        value_max = int(value_max) if is_int else float(value_max)
        settings["des_vars"][var_name] = [value_min, value_max, is_int]

    # Process output constraints settings
    for name, value_list in settings["outputs"].items():
        threshold, method, weight, calc_expr = value_list
        settings["outputs"][name] = [float(threshold), method, float(weight), calc_expr]

    settings["dependent_vars"] = settings.get("dependent_vars") or []
    settings["intentions"] = settings.get("intentions") or []

    # TODO: dependent_vars 0-1 mask

    return settings


def setup_seed(seed, deterministic=False):
    import random

    import numpy
    import torch

    os.environ["PYTHONHASHSEED"] = str(seed)

    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

    numpy.random.seed(seed)
    random.seed(seed)
    torch.backends.cudnn.enabled = True

    if not deterministic:
        return
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.enabled = False


def format_metrics_for_llm(
    metrics_dict: Dict[str, float], targets: Dict[str, Dict[str, float]]
) -> str:
    """Format metrics in a readable way for LLM"""
    lines = ["Current Performance:"]
    for metric, value in metrics_dict.items():
        line = f"  {metric}: {value:.4g}"
        if metric in targets:
            target_info = targets[metric]
            for op, target_val in target_info.items():
                status = (
                    "✓"
                    if (
                        (op == ">=" and value >= target_val) or (op == "<=" and value <= target_val)
                    )
                    else "✗"
                )
                line += f" (target: {op} {target_val:.4g}) {status}"
        lines.append(line)
    return "\n".join(lines)


def validate_llm_updates(
    updates_list: List[Dict[str, float]],
    current_params: Dict[str, float],
    bounds: Dict[str, Tuple[float, float]],
) -> List[Dict[str, float]]:
    """Validate and sanitize LLM suggested updates (3 strategies)"""
    validated_list = []

    for updates in updates_list:
        validated = {}
        for param, new_value in updates.items():
            if param not in bounds:
                continue

            min_val, max_val = bounds[param]
            current_val = current_params.get(param, 0)

            # Ensure reasonable change (max 50% change)
            max_change = 0.5 * abs(current_val)
            if abs(new_value - current_val) > max_change:
                new_value = current_val + np.sign(new_value - current_val) * max_change

            # Clamp to bounds
            new_value = max(min(new_value, max_val), min_val)
            validated[param] = float(new_value)

        validated_list.append(validated)

    return validated_list


def extract_targets_from_settings(settings: Dict) -> Dict[str, Dict[str, float]]:
    """Extract target specifications from YAML settings"""
    targets = {}
    for perf_name, perf_config in settings["outputs"].items():
        targets[perf_name] = perf_config
    return targets


def extract_param_bounds_from_settings(settings: Dict) -> Dict[str, Tuple[float, float]]:
    """Extract parameter bounds from YAML settings"""
    bounds = {}
    for param_name, (min_val, max_val, _) in settings["des_vars"].items():
        bounds[param_name] = (float(min_val), float(max_val))
    return bounds


def compute_violations(
    metrics: np.ndarray,
    targets: Dict[str, Dict[str, float]],
    performances: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, Any]]:
    """Compute which targets are violated"""
    violations = {}
    performance_names = list(performances.keys())

    for idx, perf_name in enumerate(performance_names):
        if perf_name in targets:
            target = targets[perf_name]
            current_val = metrics[idx]

            target_val, op, _, _ = target
            if op == "target":
                violations[perf_name] = {
                    "current": current_val,
                    "target": target_val,
                    "delta": target_val - current_val,
                    "condition": "to be minimized",
                    "unit": get_unit_for_performance(perf_name),
                }
            elif op == "min" and current_val < target_val:
                violations[perf_name] = {
                    "current": current_val,
                    "target": target_val,
                    "delta": target_val - current_val,
                    "condition": "at least",
                    "unit": get_unit_for_performance(perf_name),
                }
            elif op == "max" and current_val > target_val:
                violations[perf_name] = {
                    "current": current_val,
                    "target": target_val,
                    "delta": current_val - target_val,
                    "condition": "at most",
                    "unit": get_unit_for_performance(perf_name),
                }

    return violations


def get_unit_for_performance(perf_name: str) -> str:
    """Get display unit for performance metric"""
    units = {
        "gain": "dB",
        "ugb": "Hz",
        "gbw": "Hz",
        "pm": "deg",
        "phase_margin": "deg",
        "power": "W",
        "power_mw": "mW",
        "sr": "V/μs",
        "slew_rate": "V/μs",
        "cmrr": "dB",
        "psrr": "dB",
        "noise": "V/√Hz",
        "offset": "V",
    }
    return units.get(perf_name.lower(), "")
