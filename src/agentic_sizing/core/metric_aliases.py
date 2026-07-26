from __future__ import annotations

from typing import Iterable, Set

_METRIC_ALIASES: dict[str, set[str]] = {
    "slew_rate_rise": {"slew_rate_rise", "rise_time", "sr_rise", "positive_slew_rate"},
    "slew_rate_fall": {"slew_rate_fall", "fall_time", "sr_fall", "negative_slew_rate"},
    "rms_noise_out": {"rms_noise_out", "noise", "output_noise_rms"},
}


def canonical_metric_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        return normalized
    lowered = normalized.lower()
    for canonical, aliases in _METRIC_ALIASES.items():
        if lowered in {item.lower() for item in aliases}:
            return canonical
    return normalized


def normalize_metric_set(values: Iterable[str] | None) -> Set[str]:
    if values is None:
        return set()
    normalized: Set[str] = set()
    for value in values:
        if isinstance(value, str) and value.strip():
            normalized.add(canonical_metric_name(value))
    return normalized
