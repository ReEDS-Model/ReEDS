import unittest
from pathlib import Path

import pandas as pd


PR_DIR = Path(__file__).resolve().parents[1]
REEDS = PR_DIR.parents[1]
MIRROR = PR_DIR / "outputs" / "pr100_1LM_mirror"


class PR100MirrorInputTest(unittest.TestCase):
    def test_case_switches_select_the_mirror_inputs(self):
        cases = pd.read_csv(REEDS / "cases_pr.csv", index_col=0)
        mirror = cases["PR100_1LM_mirror"]
        self.assertEqual(mirror["endyear"], "2050")
        self.assertEqual(
            mirror["yearset"],
            "2010_2022_2025_2028_2030_2035_2040_2045_2050",
        )
        self.assertEqual(mirror["unitdata"], "PR100-1LM")
        self.assertEqual(mirror["incentives_suffix"], "PR100_1LM")
        self.assertEqual(mirror["GSw_StateRPS"], "1")
        self.assertEqual(mirror["GSw_OpRes"], "0")
        self.assertEqual(mirror["GSw_SkipRAyear"], "2025")
        self.assertEqual(mirror["pras_samples"], "10000")
        self.assertEqual(mirror["pras_trans_contingency"], "1")

    def test_official_capacity_benchmark_has_all_pr100_years(self):
        frame = pd.read_csv(MIRROR / "official_capacity_1LM.csv")
        self.assertEqual(
            sorted(frame["year"].unique()),
            [2022, 2025, 2028, 2030, 2035, 2040, 2045, 2050],
        )
        self.assertEqual(len(frame), 144)

    def test_forced_distpv_is_annual_and_matches_report_years(self):
        frame = pd.read_csv(
            REEDS / "inputs" / "dgen_model_inputs" / "pr100_1LM"
            / "distpvcap_pr100_1LM.csv"
        )
        self.assertEqual(
            [int(column) for column in frame.columns[1:]], list(range(2010, 2051))
        )
        expected = {
            2022: 450.793456003,
            2025: 771.534084800,
            2028: 954.541735650,
            2030: 1063.448164980,
            2035: 1246.199758250,
            2040: 1443.744306890,
            2045: 1855.672698080,
            2050: 2473.946480950,
        }
        for year, total in expected.items():
            self.assertAlmostEqual(frame[str(year)].sum(), total, places=6)

    def test_rps_schedule(self):
        rps = pd.read_csv(MIRROR / "rps_fraction.csv").set_index("t")
        self.assertEqual(rps.loc[2024, "rps_all"], 0.0)
        self.assertEqual(rps.loc[2025, "rps_all"], 0.4)
        self.assertEqual(rps.loc[2039, "rps_all"], 0.4)
        self.assertEqual(rps.loc[2040, "rps_all"], 0.6)
        self.assertEqual(rps.loc[2050, "rps_all"], 1.0)

    def test_published_cost_normalizations(self):
        upv = pd.read_csv(
            REEDS / "inputs" / "plant_characteristics" / "upv_PR100_1LM.csv"
        ).set_index("t")
        self.assertAlmostEqual(upv.loc[2025, "capcost"], 1657.0, places=6)
        self.assertAlmostEqual(upv.loc[2025, "fom"], 29.09, places=6)
        battery = pd.read_csv(
            REEDS / "inputs" / "plant_characteristics" / "battery_PR100_1LM.csv"
        ).set_index("t")
        self.assertAlmostEqual(battery.loc[2025, "capcost"], 672.9, places=6)
        self.assertAlmostEqual(battery.loc[2025, "capcost_energy"], 644.1, places=6)
        self.assertAlmostEqual(battery.loc[2025, "rte"], 0.85, places=6)

    def test_pr100_itc_path_has_no_ptc_or_bonus(self):
        incentives = pd.read_csv(
            REEDS / "inputs" / "financials" / "incentives_PR100_1LM.csv"
        )
        self.assertTrue((incentives["ptc_value"] == 0).all())
        self.assertTrue((incentives["itc_percpt_domestic_bonus"] == 0).all())
        by_year = incentives.groupby("t_start_construction")["itc_frac"].first()
        self.assertEqual(by_year.loc[2033], 0.30)
        self.assertEqual(by_year.loc[2034], 0.15)
        self.assertEqual(by_year.loc[2035], 0.0)

    def test_transmission_interfaces_are_complete(self):
        frame = pd.read_csv(MIRROR / "interfaces_itl_pr100.csv")
        self.assertEqual(len(frame), 184)
        self.assertEqual((frame["method"] == "sum_of_boundary_continuous_ratings").sum(), 172)
        self.assertEqual((frame["method"] == "N0_TTC_fallback_no_rated_boundary").sum(), 12)
        self.assertTrue((frame["MW"] > 0).all())
        self.assertTrue(frame["loss"].between(0, 0.2).all())

    def test_report_hydro_assumption_overrides_benchmark_inconsistency(self):
        units = pd.read_csv(MIRROR / "unitdata_provenance.csv")
        hydro = units.loc[units["tech"] == "hydED"].iloc[0]
        self.assertAlmostEqual(hydro["capacity_mw"], 10.0, places=6)
        self.assertEqual(hydro["retire_year"], 2051)


if __name__ == "__main__":
    unittest.main()
