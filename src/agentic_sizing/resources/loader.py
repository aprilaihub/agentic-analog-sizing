"""Helpers for reading package data from installed wheels and source trees."""

from __future__ import annotations

from importlib.resources import files


def read_text(*parts: str) -> str:
    """Read a UTF-8 text resource relative to ``agentic_sizing.resources``."""
    resource = files("agentic_sizing.resources").joinpath(*parts)
    if not resource.is_file():
        raise FileNotFoundError(f"Package resource not found: {'/'.join(parts)}")
    return resource.read_text(encoding="utf-8")
