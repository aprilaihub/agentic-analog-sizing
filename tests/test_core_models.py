import unittest

from agentic_sizing.core.models import SpecConstraint, to_jsonable


class CoreModelsTest(unittest.TestCase):
    def test_to_jsonable_serializes_dataclass_instance(self) -> None:
        value = SpecConstraint(name="gain", target=60.0, relation="min")

        self.assertEqual(
            to_jsonable(value),
            {"name": "gain", "target": 60.0, "relation": "min", "weight": 1.0},
        )

    def test_to_jsonable_does_not_serialize_dataclass_type(self) -> None:
        self.assertIs(to_jsonable(SpecConstraint), SpecConstraint)


if __name__ == "__main__":
    unittest.main()
