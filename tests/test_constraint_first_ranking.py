import unittest

import numpy as np
from agentic_sizing.simulator import interfacing


class ConstraintFirstRankingTest(unittest.TestCase):
    def test_infeasible_corner_is_selected_as_worst(self):
        settings = {
            "objective": {"name": "power", "minormax": "min"},
            "outputs": {
                "power": [1e-3, "target", 1.0, "*value"],
                "gain": [100.0, "min", 1.0, "*value"],
            },
        }
        responses = {
            "power": [1e-6, 1e-3],
            "gain": [50.0, 100.0],
        }

        selected = interfacing.calc_outputs(value_nums=1, responses=responses, settings=settings)

        np.testing.assert_allclose(selected, [[1e-6, 50.0]])


if __name__ == "__main__":
    unittest.main()
