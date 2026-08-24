import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "prepare_pr_nodal.py"
SPEC = importlib.util.spec_from_file_location("prepare_pr_nodal", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MultiSourceAssignmentTest(unittest.TestCase):
    def test_impedance_and_stable_tie_break(self):
        adjacency = {
            1: [(2, 1.0)],
            2: [(1, 1.0), (3, 1.0), (4, 0.25)],
            3: [(2, 1.0)],
            4: [(2, 0.25)],
            9: [],
        }
        owner, distance, hops = MODULE.multi_source_assignment(
            adjacency, [1, 3], adjacency
        )
        self.assertEqual(owner[2], 1)
        self.assertEqual(owner[4], 1)
        self.assertEqual(distance[4], 1.25)
        self.assertEqual(hops[4], 2)
        self.assertNotIn(9, owner)


class InterfaceAggregationTest(unittest.TestCase):
    def test_internal_and_unmapped_branches_are_not_interfaces(self):
        branches = [
            {
                "from_region": "pr1",
                "to_region": "pr2",
                "rate_mw_assuming_system_base": 100.0,
                "suspect_unlimited_rating": False,
            },
            {
                "from_region": "pr2",
                "to_region": "pr1",
                "rate_mw_assuming_system_base": 50.0,
                "suspect_unlimited_rating": True,
            },
            {
                "from_region": "pr1",
                "to_region": "pr1",
                "rate_mw_assuming_system_base": 999.0,
                "suspect_unlimited_rating": False,
            },
            {
                "from_region": "",
                "to_region": "pr1",
                "rate_mw_assuming_system_base": 999.0,
                "suspect_unlimited_rating": False,
            },
        ]
        rows = MODULE.build_interfaces(branches)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["branch_count"], 2)
        self.assertEqual(rows[0]["boundary_rate_sum_mw_screening_only"], 150.0)
        self.assertEqual(rows[0]["suspect_rating_count"], 1)


if __name__ == "__main__":
    unittest.main()
