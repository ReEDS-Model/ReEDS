import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "prepare_pr_supply_curves.py"
SPEC = importlib.util.spec_from_file_location("prepare_pr_supply_curves", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class HaversineTest(unittest.TestCase):
    def test_zero_and_one_degree(self):
        self.assertEqual(MODULE.haversine_km(18, -66, 18, -66), 0.0)
        self.assertAlmostEqual(MODULE.haversine_km(0, 0, 1, 0), 111.195, places=3)


class WeightedClassesTest(unittest.TestCase):
    def test_classes_are_monotonic_and_bounded(self):
        rows = [
            {"sc_point_gid": str(i), "cf": cf, "capacity": 1.0}
            for i, cf in enumerate((0.1, 0.2, 0.3, 0.4), start=1)
        ]
        MODULE.weighted_classes(rows, 2)
        self.assertEqual([row["class"] for row in rows], [1, 1, 2, 2])


if __name__ == "__main__":
    unittest.main()
