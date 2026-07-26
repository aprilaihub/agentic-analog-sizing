from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.initialization.record_store import (
    append_simulation_record,
    get_runtime_summary_path,
    load_simulation_records,
    write_runtime_summary,
)
from agentic_sizing.initialization.schemas import InitializeSchemaValidationError


class TestSimulationRecordStore(unittest.TestCase):
    def test_append_creates_file_and_assigns_iter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            record_path = Path(td) / "simulation_record.json"
            record = append_simulation_record(
                str(record_path),
                parameters=[1.0, 2.0],
                performance=[3.0, 4.0],
            )

            self.assertEqual(record["iter"], 1)
            self.assertEqual(record["parameters"], [1.0, 2.0])
            self.assertEqual(record["performance"], [3.0, 4.0])
            self.assertNotIn("cost_time_s", record)

            payload = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["iter"], 1)

    def test_append_auto_increments_and_handles_conflict_iter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            record_path = Path(td) / "simulation_record.json"

            first = append_simulation_record(
                str(record_path),
                parameters=[1.0],
                performance=[10.0],
                iteration=1,
            )
            second = append_simulation_record(
                str(record_path),
                parameters=[2.0],
                performance=[20.0],
                iteration=1,
            )

            self.assertEqual(first["iter"], 1)
            self.assertEqual(second["iter"], 2)

            records = load_simulation_records(str(record_path))
            self.assertEqual([item["iter"] for item in records], [1, 2])

    def test_append_persists_optional_cost_time_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            record_path = Path(td) / "simulation_record.json"

            record = append_simulation_record(
                str(record_path),
                parameters=[1.0],
                performance=[3.0],
                cost_time_s=1.25,
            )

            self.assertEqual(record["cost_time_s"], 1.25)

            payload = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["cost_time_s"], 1.25)

            summary_path = Path(get_runtime_summary_path(str(record_path)))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["iterations"], 1)
            self.assertEqual(summary["timed_iterations"], 1)
            self.assertEqual(summary["untimed_iterations"], 0)
            self.assertEqual(summary["total_recorded_simulation_runtime_s"], 1.25)

    def test_load_legacy_file_without_timing_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            record_path = Path(td) / "simulation_record.json"
            record_path.write_text(
                json.dumps(
                    [
                        {
                            "iter": 1,
                            "parameters": [1.0, 2.0],
                            "performance": [3.0, 4.0],
                        }
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            records = load_simulation_records(str(record_path))
            self.assertEqual(records[0]["iter"], 1)
            self.assertNotIn("cost_time_s", records[0])

    def test_write_runtime_summary_includes_wall_clock_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            record_path = Path(td) / "simulation_record.json"
            append_simulation_record(
                str(record_path),
                parameters=[1.0],
                performance=[3.0],
                cost_time_s=0.75,
            )

            summary = write_runtime_summary(
                str(record_path),
                run_started_at_unix_s=10.0,
                run_started_at_utc="2026-03-19T00:00:10+00:00",
                run_finished_at_unix_s=16.5,
                run_finished_at_utc="2026-03-19T00:00:16.500000+00:00",
                termination_reason="all_specs_met",
            )

            self.assertEqual(summary["total_recorded_simulation_runtime_s"], 0.75)
            self.assertEqual(summary["total_wall_clock_runtime_s"], 6.5)
            self.assertEqual(summary["termination_reason"], "all_specs_met")

    def test_load_invalid_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            record_path = Path(td) / "simulation_record.json"
            record_path.write_text("{}\n", encoding="utf-8")

            with self.assertRaises(InitializeSchemaValidationError):
                load_simulation_records(str(record_path))


if __name__ == "__main__":
    unittest.main()
