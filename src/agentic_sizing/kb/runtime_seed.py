from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict

from ..workflow.state import PROJECT_ROOT

_KB_VIEW_SUFFIXES = (
    "perf_tradeoff",
    "substruct_param_perf",
    "role_perf",
)


class RuntimeKBSeedError(RuntimeError):
    """Raised when runtime KB files cannot be prepared from seed files."""


def prepare_runtime_kb_from_seed(
    case_name: str,
) -> Dict[str, Any]:
    normalized_case_name = _normalize_case_name(case_name)
    seed_name = "global"

    output_kb_dir = PROJECT_ROOT / "output" / "kb"
    pillars_dir = output_kb_dir / "pillars"

    expected_source_files = {
        suffix: pillars_dir / f"{seed_name}_kb_{suffix}.json" for suffix in _KB_VIEW_SUFFIXES
    }

    available_related_files = _scan_related_seed_files(pillars_dir)
    missing_files = [str(path) for path in expected_source_files.values() if not path.exists()]

    invalid_files: list[str] = []
    for path in expected_source_files.values():
        if not path.exists():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            invalid_files.append(f"{path}: {exc}")

    if missing_files or invalid_files:
        expected_files = [str(path) for path in expected_source_files.values()]
        raise RuntimeKBSeedError(
            "runtime KB seed preparation failed. "
            f"seed_name={seed_name!r}, case_name={normalized_case_name!r}, "
            f"expected_files={expected_files}, "
            f"missing_files={missing_files}, "
            f"invalid_files={invalid_files}, "
            f"available_related_files={available_related_files}"
        )

    target_runtime_files = {
        suffix: output_kb_dir / f"{normalized_case_name}_kb_{suffix}.json"
        for suffix in _KB_VIEW_SUFFIXES
    }
    for suffix, source_path in expected_source_files.items():
        target_path = target_runtime_files[suffix]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)

    return {
        "case_name": normalized_case_name,
        "seed_name": seed_name,
        "source_dir": str(pillars_dir),
        "copied_files": {suffix: str(path) for suffix, path in target_runtime_files.items()},
    }


def _normalize_case_name(case_name: str) -> str:
    normalized = str(case_name).strip()
    if not normalized:
        raise ValueError("case_name must be a non-empty string")
    return normalized


def _scan_related_seed_files(pillars_dir: Path) -> list[str]:
    if not pillars_dir.exists() or not pillars_dir.is_dir():
        return []

    related = [
        path.name
        for path in pillars_dir.iterdir()
        if path.is_file() and "_kb_" in path.name and path.suffix == ".json"
    ]
    related.sort()
    return related
