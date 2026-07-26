from __future__ import annotations

import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
AGENTIC_SIZING_ROOT = TESTS_DIR.parent
from agentic_sizing.core.operation_region import (
    build_operation_region_summary_from_metric_map,
    extract_operation_region_targets_from_settings,
    filter_core_performance_metrics,
    filter_operation_region_summary_for_role,
)
from agentic_sizing.specs.extract_design_specs import (
    extract_design_specs_from_settings,
)


class TestOperationRegionHelpers(unittest.TestCase):
    def test_design_specs_ignore_region_outputs(self) -> None:
        settings = {
            "des_vars": {"w": [1.0, 2.0, 0]},
            "responses": {"assembler": ["power", "psr", "region_m1", "region_m2", "gm1"]},
            "outputs": {
                "power": [1.0, "target", 1.0, "*value"],
                "psr": [-40.0, "max", 1.0, "*value"],
                "region_m1": [3.0, "target", 0.0, "*value"],
                "region_m2": [3.0, "target", 0.0, "*value"],
                "gm1": [1.2e-6, "target", 0.0, "*value"],
            },
            "objective": {"name": "power", "minormax": "min"},
        }

        payload = extract_design_specs_from_settings(settings, "bgr")
        metric_names = [item["name"] for item in payload["performance_specs"]]
        self.assertEqual(metric_names, ["power", "psr"])

    def test_filter_core_performance_metrics_ignores_region_and_gm(self) -> None:
        self.assertEqual(
            filter_core_performance_metrics(["power", "region_m1", "gm1", "psr"]),
            ["power", "psr"],
        )

    def test_filter_region_summary_for_role(self) -> None:
        summary = build_operation_region_summary_from_metric_map(
            {
                "region_m19": 3.0,
                "region_m12": 2.0,
                "region_m5": 1.0,
                "region_m99": 0.0,
                "gm19": 11.0e-6,
                "gm12": 8.0e-6,
            }
        )
        targets = extract_operation_region_targets_from_settings(
            {
                "outputs": {
                    "region_m19": [3.0, "target", 0.0, "*value"],
                    "region_m12": [3.0, "target", 0.0, "*value"],
                    "region_m5": [3.0, "target", 0.0, "*value"],
                }
            }
        )
        role_substructures = [
            {"devices": ["M19", "M12", "M5"]},
            {"devices": ["M12"]},
        ]

        filtered = filter_operation_region_summary_for_role(summary, role_substructures, targets)
        self.assertEqual(filtered["available_device_count"], 3)
        self.assertEqual(
            filtered["role_device_regions"],
            [
                {"device": "M19", "region": "subthreshold", "target_region": "subthreshold"},
                {"device": "M12", "region": "saturation", "target_region": "subthreshold"},
                {"device": "M5", "region": "triode", "target_region": "subthreshold"},
            ],
        )
        self.assertEqual(
            filtered["role_device_gms"],
            [
                {"device": "M19", "gm": 11.0e-6},
                {"device": "M12", "gm": 8.0e-6},
            ],
        )


if __name__ == "__main__":
    unittest.main()
