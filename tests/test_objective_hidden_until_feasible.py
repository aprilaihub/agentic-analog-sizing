import unittest

from agentic_sizing.iteration.context import evaluate_unsatisfied_metrics


class ObjectiveHiddenUntilFeasibleTest(unittest.TestCase):
    def test_objective_target_is_hidden_while_constraints_fail(self):
        design_specs = {
            "objective": {
                "metric": "power",
                "sense": "min",
            },
            "performance_specs": [
                {
                    "name": "power",
                    "index": 0,
                    "method": "target",
                    "threshold": 1e-3,
                    "is_objective": True,
                },
                {
                    "name": "pm",
                    "index": 1,
                    "method": "min",
                    "threshold": 60.0,
                    "is_objective": False,
                },
            ],
        }

        unsatisfied = evaluate_unsatisfied_metrics({"power": 2e-3, "pm": 10.0}, design_specs)

        self.assertEqual([item["name"] for item in unsatisfied], ["pm"])

    def test_objective_target_returns_after_constraints_pass(self):
        design_specs = {
            "objective": {
                "metric": "power",
                "sense": "min",
            },
            "performance_specs": [
                {
                    "name": "power",
                    "index": 0,
                    "method": "target",
                    "threshold": 1e-3,
                    "is_objective": True,
                },
                {
                    "name": "pm",
                    "index": 1,
                    "method": "min",
                    "threshold": 60.0,
                    "is_objective": False,
                },
            ],
        }

        unsatisfied = evaluate_unsatisfied_metrics({"power": 2e-3, "pm": 70.0}, design_specs)

        self.assertEqual([item["name"] for item in unsatisfied], ["power"])


if __name__ == "__main__":
    unittest.main()
