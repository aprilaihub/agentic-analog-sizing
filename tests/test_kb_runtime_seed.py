from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.kb.runtime_seed import RuntimeKBSeedError, prepare_runtime_kb_from_seed


class TestRuntimeKBSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        self.project_root = Path(self.tempdir.name) / "agenticSizing"
        self.pillars_dir = self.project_root / "output" / "kb" / "pillars"
        self.runtime_kb_dir = self.project_root / "output" / "kb"
        self.pillars_dir.mkdir(parents=True, exist_ok=True)

    def _write_seed_files(self, seed_name: str) -> dict[str, Path]:
        payloads = {
            "perf_tradeoff": {"facts": [{"type": "perf_perf_tradeoff", "seed": seed_name}]},
            "substruct_param_perf": {
                "facts": [{"type": "substruct_param_perf", "seed": seed_name}]
            },
            "role_perf": {"facts": [{"type": "role_perf", "seed": seed_name}]},
        }
        files: dict[str, Path] = {}
        for suffix, payload in payloads.items():
            path = self.pillars_dir / f"{seed_name}_kb_{suffix}.json"
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
            )
            files[suffix] = path
        return files

    def _prepare(self, case_name: str, seed_name: str) -> dict:
        self.assertEqual(seed_name, "global")
        with patch("agentic_sizing.kb.runtime_seed.PROJECT_ROOT", self.project_root):
            return prepare_runtime_kb_from_seed(case_name=case_name)

    def test_prepare_global_seed_copies_three_files(self) -> None:
        self._write_seed_files("global")

        result = self._prepare(case_name="5t_ota", seed_name="global")
        self.assertEqual(result["seed_name"], "global")

        for suffix in ("perf_tradeoff", "substruct_param_perf", "role_perf"):
            source = self.pillars_dir / f"global_kb_{suffix}.json"
            target = self.runtime_kb_dir / f"5t_ota_kb_{suffix}.json"
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))

    def test_prepare_overwrites_existing_runtime_files(self) -> None:
        self._write_seed_files("global")
        old_target = self.runtime_kb_dir / "5t_ota_kb_role_perf.json"
        old_target.parent.mkdir(parents=True, exist_ok=True)
        old_target.write_text('{"facts":[{"stale":true}]}\n', encoding="utf-8")

        self._prepare(case_name="5t_ota", seed_name="global")

        replaced = json.loads(old_target.read_text(encoding="utf-8"))
        self.assertEqual(replaced["facts"][0]["seed"], "global")

    def test_prepare_does_not_modify_pillars_seed_files(self) -> None:
        source_files = self._write_seed_files("global")
        before_text = {
            suffix: path.read_text(encoding="utf-8") for suffix, path in source_files.items()
        }

        self._prepare(case_name="5t_ota", seed_name="global")

        after_text = {
            suffix: path.read_text(encoding="utf-8") for suffix, path in source_files.items()
        }
        self.assertEqual(after_text, before_text)

    def test_prepare_missing_seed_file_raises_clear_error(self) -> None:
        self._write_seed_files("global")
        (self.pillars_dir / "global_kb_role_perf.json").unlink()

        with patch("agentic_sizing.kb.runtime_seed.PROJECT_ROOT", self.project_root):
            with self.assertRaises(RuntimeKBSeedError) as exc:
                prepare_runtime_kb_from_seed(case_name="5t_ota")

        message = str(exc.exception)
        self.assertIn("seed_name='global'", message)
        self.assertIn("missing_files=", message)
        self.assertIn("global_kb_role_perf.json", message)
        self.assertIn("available_related_files=", message)


if __name__ == "__main__":
    unittest.main()
