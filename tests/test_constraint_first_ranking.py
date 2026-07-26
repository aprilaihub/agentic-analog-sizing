import unittest

import numpy as np
from agentic_sizing.simulator.interfacing import _get_violation_ranking


class ConstraintFirstRankingTest(unittest.TestCase):
    def test_constraints_beat_lower_objective(self):
        settings = {
            "objective": {"name": "power", "minormax": "min"},
            "outputs": {
                "power": [1e-3, "target", 1.0, "*value"],
                "gain": [100.0, "min", 1.0, "*value"],
            },
        }
        performances = np.array(
            [
                [1e-6, 50.0],  # lower power, infeasible gain
                [1e-3, 100.0],  # higher power, feasible
            ]
        )

        best_idx, worst_idx, ranks = _get_violation_ranking(performances, settings)

        self.assertEqual(best_idx, 1)
        self.assertEqual(worst_idx, 0)
        self.assertLess(ranks[1], ranks[0])


if __name__ == "__main__":
    unittest.main()
