"""optimize_goal tools and contracts."""

from __future__ import annotations

from typing import Any


def extract_design_specs_from_settings(settings: dict[str, Any], topology: str) -> dict[str, Any]:
    from .extract_design_specs import extract_design_specs_from_settings as _impl

    return _impl(settings=settings, topology=topology)


def extract_design_specs_file(
    input_settings_path: str, output_path: str | None = None
) -> dict[str, Any]:
    from .extract_design_specs import extract_design_specs_file as _impl

    return _impl(input_settings_path=input_settings_path, output_path=output_path)


__all__ = ["extract_design_specs_from_settings", "extract_design_specs_file"]
