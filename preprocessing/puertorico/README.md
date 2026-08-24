# Puerto Rico `>=115 kV` nodal ReEDS case

This directory builds a 121-region Puerto Rico ReEDS model from connected transmission buses at or above 115 kV. The spatial construction follows Karmakar and Cole (2024): lower-voltage buses and assets are electrically assigned to retained nodes, and the source network defines the interregional topology.

Two case columns are retained in `cases_pr.csv`:

- `PR_115plus_input` is the earlier 2010–2030 integration/smoke case.
- `PR100_1LM_mirror` is the 2010 bookkeeping plus 2022–2050 PR100 1LM calibration case. This is the case to run for PR100 comparison.

The mirror case now includes the public PR100 annual DER trajectory, renewable targets, annual technology-cost trajectories, aggregate fleet and retirement schedule, Tranche 1/required storage additions, fuel-price proxies, fixed transmission assumptions, multi-year PRAS settings, and the official PR100 capacity benchmark. It has passed the full input/GDX/GAMS build and generated a 43,512-row first-year LP; this machine stopped only at its CPLEX demo-license limit. See `METHODOLOGY.md` for exact derivations and limitations.

## Build all inputs

Run from `/projects/aiplusinvest/ychen10/ReEDS` with the ReEDS Python environment:

```bash
PRPY=/home/ychen10/.conda-envs/reeds/bin/python

$PRPY preprocessing/puertorico/prepare_pr_nodal.py
$PRPY preprocessing/puertorico/prepare_pr_supply_curves.py
$PRPY preprocessing/puertorico/convert_pr_profiles.py
$PRPY preprocessing/puertorico/prepare_pr100_load.py
$PRPY preprocessing/puertorico/prepare_pr100_der_committed.py
$PRPY preprocessing/puertorico/calculate_pr_itl.py
$PRPY preprocessing/puertorico/validate_pr_staging.py
$PRPY preprocessing/puertorico/prepare_pr_explicit_zone.py
$PRPY preprocessing/puertorico/prepare_pr_reeds_inputs.py
$PRPY preprocessing/puertorico/prepare_pr100_mirror.py

$PRPY -m unittest discover -s preprocessing/puertorico/tests -v
```

The source data default to `/projects/aiplusinvest/base_case`, `/projects/aiplusinvest/pr100_all`, `/projects/aiplusinvest/pr100_rev`, `/projects/aiplusinvest/pr100_rev_profiles`, and `/projects/aiplusinvest/pr100_rev_scripts`.

`prepare_pr100_mirror.py` must run after the native-input scripts. It reads the official OEDI `IntegratedCapacityInvestment.zip` archive, writes the exact PR100 1LM capacity benchmark, and generates the case-specific policy, DER, unit, cost, fuel, and transmission inputs.

## Launch the PR100 mirror case

```bash
module use /nopt/nrel/apps/software/gams/modulefiles
module load gams/53.5.1

env -u NREL_CLUSTER \
  PATH=/home/ychen10/.conda-envs/reeds/bin:/nopt/nrel/apps/software/gams/53.5.1:/usr/local/bin:/usr/bin:/bin \
  $PRPY -u runreeds.py \
  -b pr100_mirror -c pr -s PR100_1LM_mirror -l -f
```

Omit `-l` for normal cluster submission. The case has `input_processing_only=0`; a GAMS installation with a licensed large-scale solver is required for optimization.

## Compare with the original PR100 result

After the run finishes:

```bash
$PRPY preprocessing/puertorico/compare_pr100_capacity.py \
  runs/pr100_mirror_PR100_1LM_mirror
```

This writes `outputs/pr100_capacity_comparison.csv` and a yearly summary inside the run directory. The untouched official technology/year data are staged at `preprocessing/puertorico/outputs/pr100_1LM_mirror/official_capacity_1LM.csv`.

## Important replication limits

- Public PR100 files do not contain the proprietary Engage/LUMA unit-level workbook or final PPOA inputs. The mirror reproduces official aggregate capacities and retirement steps, then allocates them to source-network regions. It implements the public PR100 ITC path, but PPOA inflation and contractual-finance terms remain unavailable.
- Fuel prices are approximate digitizations of PR100 report Figure 132.
- ReEDS accepts annual technology costs, but this implementation uses one fixed 2035 PR100 resource geometry/profile set. Later public onshore/offshore supply curves are unavailable.
- ReEDS representative-day sampling with three-hour chunks is not identical to Engage's three custom hourly extreme periods plus six-hour treatment of the remaining year.
- Existing DPV is absent from the published 2022 Engage capacity table, so the 450.793 MW DER-archive baseline is used in 2022; published Engage totals are forced from 2025 onward.
- Distributed-PV production uses a regional utility-PV profile proxy because public nodal rooftop-PV profiles were not released.
- PRAS runs for each 2025–2050 expansion year with 2019 weather and 10,000 samples. It uses a 15% PRM-transfer derate and ReEDS static generator outages because PR100's event-level generator and transmission outage draws are not public.

Reference: Akash Karmakar and Wesley Cole, *Nodal Capacity Expansion Modeling with ReEDS: A Case Study of the RTS-GMLC Test System*, NREL/TP-6A40-87870 (2024), https://docs.nlr.gov/docs/fy24osti/87870.pdf.
