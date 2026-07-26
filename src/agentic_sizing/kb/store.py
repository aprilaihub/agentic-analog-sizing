from __future__ import annotations

import json
import os
from typing import Any, Dict

from ..core.models import to_jsonable


def load_planner_kb(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_worker_kb(role_id: str, workers_dir: str, template_path: str) -> Dict[str, Any]:
    role_file = os.path.join(workers_dir, f"{role_id}.json")
    candidate = role_file if os.path.exists(role_file) else template_path
    if not os.path.exists(candidate):
        return {}
    with open(candidate, "r", encoding="utf-8") as f:
        return json.load(f)


def append_episode(record: Dict[str, Any], episodes_path: str) -> None:
    os.makedirs(os.path.dirname(episodes_path), exist_ok=True)
    payload = to_jsonable(record)
    with open(episodes_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")
