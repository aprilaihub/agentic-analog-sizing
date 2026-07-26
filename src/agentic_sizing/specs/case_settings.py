from __future__ import annotations

import json
from pathlib import Path

from ..simulator.utils import parse_yaml
from ..workflow.state import PACKAGE_ROOT, PROJECT_ROOT


def _settings_path_for_case(case_name: str) -> Path:
    return PROJECT_ROOT / "input" / "kb" / f"{case_name}_settings.json"


def _yaml_candidates_for_case(case_name: str) -> list[Path]:
    file_names = [f"{case_name}.yaml", f"{case_name}.yml"]
    search_roots = [PACKAGE_ROOT / "simulator" / "yaml_settings"]
    return [root / file_name for root in search_roots for file_name in file_names]


def resolve_case_yaml_path(case_name: str) -> Path:
    normalized = str(case_name or "").strip()
    if not normalized:
        raise ValueError("case_name must be a non-empty string")

    for candidate in _yaml_candidates_for_case(normalized):
        if candidate.exists():
            return candidate.resolve()

    checked = "\n".join(f"- {path}" for path in _yaml_candidates_for_case(normalized))
    raise FileNotFoundError(
        f"Could not find a YAML settings source for case {normalized!r}. Checked:\n{checked}"
    )


def materialize_case_settings_json(case_name: str, settings_path: str | Path | None = None) -> Path:
    normalized = str(case_name or "").strip()
    if not normalized:
        raise ValueError("case_name must be a non-empty string")

    target_path = (
        Path(settings_path).expanduser().resolve()
        if settings_path is not None
        else _settings_path_for_case(normalized).resolve()
    )

    try:
        yaml_path = resolve_case_yaml_path(normalized)
    except FileNotFoundError:
        if target_path.exists():
            return target_path
        raise

    settings = parse_yaml(str(yaml_path))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return target_path
