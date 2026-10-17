# Usage and results (detailed reference)

This is the detailed run guide and full results record. Start with the top-level `README.md`; the formulation is in `FORMULATION.md` at the project root. Commands below run from the project root.

A 17-equation subset of ReEDS `c_model.gms` (plus an objective in the ReEDS style), implemented twice, in **pyoframe** and **Pyomo**, on one shared data layer. The math is in `FORMULATION.md`.

```
reeds_slice/
  contract.py        data contract: raw tables (GAMS symbols + slice_* + state_*), loader, checks
  prep.py            shared polars layer: variable/constraint domains and term coefficients
  build_pyoframe.py  algebra in pyoframe   (~90 code lines)
  build_pyomo.py     algebra in Pyomo      (~200 code lines, "fast Pyomo" pre-indexed style)
  build_pyoframe_mip.py  second pyoframe formulation: integer plant investment (whole units)
  ptdf.py            PTDF network layer: line flows from a user line list and reference zone (pyoframe + Pyomo)
  kkt.py             verifies any (primal, dual) pair against the model
  report.py          ReEDS-style outputs (report.gms / report_calcs.py definitions, outputs.h5 layout)
  duals.py           every equation's dual in GAMS results.gdx layout, plus tool comparison
  synthetic.py       ReEDS-shaped synthetic case in the contract format
  solvers.py         makes the highspy wheel visible to pyoptinterface
run_bakeoff.py       build, solve, compare; writes a JSON report
run_mip.py           LP vs integer-investment MIP, fix-and-resolve prices, checks 1-5
run_ptdf.py          PTDF network (user lines, user reference zone) vs the transport model, checks 1-6
FORMULATION.md       equations, domains, export definitions, conventions
```

## Run

```bash
pip install -r requirements.txt
python run_bakeoff.py --highs-solver ipm                              # synthetic, ~2.8k rows
python run_bakeoff.py --regions 40 --rep-days 12 --stress-days 2 --highs-solver ipm
python run_bakeoff.py --regions 80 --rep-days 24 --stress-days 2 --build-only --only pyomo
python run_bakeoff.py --case runs/<case>/slice_export --highs-solver ipm  # real ReEDS export
python run_bakeoff.py --highs-solver ipm --outputs results/              # + ReEDS outputs and all duals
```

For clean memory numbers, run each tool in its own process with `--only`.

## Gates

| Gate | Test |
|---|---|
| 1 structure | Rows per equation family match in both models and the prep domains. |
| 2 objective | Relative difference ≤ 1e-6. |
| 3 cross-check | pyoframe's primal is plugged into the Pyomo model; every row must hold and the objective must reproduce. |
| 4 KKT | Each tool's duals must satisfy sign, stationarity and complementarity on the Pyomo model. |
| info | Element-wise dual differences. These can be nonzero on degenerate rows even when both duals are valid. |

## Results so far (synthetic case)

Environment: 1 CPU, ~4 GB RAM, HiGHS 1.15.1 IPM, pyoframe 1.9.1, Pyomo 6.10.1.

| Size (rows / columns) | Gates | pyoframe build | Pyomo build* | pyoframe peak RSS | Pyomo peak RSS |
|---|---|---|---|---|---|
| 2.8k / 2.7k | all pass | 0.13 s | 0.19 s | n/a | n/a |
| 102k / 99k | all pass | 0.93 s | 7.4 s | 367 MB | 638 MB |
| 378k / 365k | build only | 3.6 s | 37.5 s | 566 MB | 1,617 MB |

\*Pyomo build = model construction (2.3 s at 102k rows) + translation into HiGHS (5.1 s). pyoframe writes directly into the solver while building. Peak RSS is for the whole process, including case generation and prep, which are the same for both.

Observations:

- Both formulations produce the same LP. The objective matches to about 1e-9, and pyoframe's primal-dual pair is KKT-optimal on the Pyomo model.
- Element-wise duals differ on degenerate rows, while both pass KKT. The GAMS comparison must therefore use the KKT gate or aggregate prices, not row-by-row marginals.
- pyoframe returns correct HiGHS duals, even though its solver table flags HiGHS duals as unsupported.
- Solve time differed (12.9 s vs 18.2 s at 102k rows) in early runs with the same algorithm. Later runs were close (13.6 s vs 14.4 s), so this looks like run-to-run variation tied to column order, not a modeling difference.
- **Reproducibility.** pyoframe gives identical primal and dual solutions run to run, since `prep` sorts every table. Pyomo does not: both of its HiGHS interfaces (`appsi` and `pyomo.contrib.solver`) order columns differently from run to run, even with a fixed `PYTHONHASHSEED`. A degenerate LP then lands on a different optimal vertex each time. Every vertex passes the KKT gate, but hourly dispatch and degenerate-row duals change between identical runs. A mitigation to test is Pyomo's LP writer with `file_determinism`.

## Outputs (`--outputs DIR`)

```
DIR/
  pyoframe/outputs/outputs.h5   ReEDS layout, readable with reeds.io.read_output / read_h5
  pyoframe/outputs/{key}.csv    same tables as CSV
  pyoframe/duals/eq_*.csv       every row of every equation: domain, Level, Lower, Upper,
                                Marginal, sense, Slack (GAMS results.gdx layout)
  pyoframe/duals/duals.h5       the same, in the ReEDS h5 layout
  pyomo/...                     same structure for Pyomo
  dual_comparison.csv           every row: both marginals, abs diff, slacks, binding flags
  dual_summary.csv              per equation: rows, nonzero marginals, rows differing, max diff
  outputs_comparison.csv        per ReEDS output: max abs diff between tools
  gates.json                    gates 1-4 detail
```

The ReEDS-style outputs (36 keys) use ReEDS key names, columns and units, following `report.gms` and `report_calcs.py`:
- **Capacity:** `cap` (cap_out), `cap_ivrt`, `cap_deg_ivrt`, `cap_energy_ivrt`, `cap_new_ivrt`, `cap_new_out`, `cap_new_bin_out`, `cap_energy_new_out`
- **Generation:** `gen_h`, `gen_h_stress`, `gen_ivrt`, `gen_ann`, `curt_h`
- **Storage:** `stor_in`, `stor_out`, `stor_level`, `stor_inout`
- **Load and prices:** `load_rt`, `reqt_price`, `reqt_quant`, `reqt_price_sys`, `reqt_quant_sys`, `co2_price`
- **Emissions:** `emit_r`, `emit_nat`, `emit_irt`
- **Transmission:** `tran_cap_energy`, `tran_cap_prm`, `tran_out`, `tran_prm_out`, `tran_flow_*`, `losses_tran_h`, `invtran_out`
- **Objective:** `objfn_raw`

ReEDS outputs that depend on parts of the model outside the slice are not produced.

Raw marginals are in objective units (cost_scale × present value). ReEDS converts the ones it reports as prices with `(1/cost_scale)·(1/pvf_onm(t))`, dividing by `hours(h)` for $/MWh. Those are in `reqt_price` and `co2_price`.

## Integer plant investment (`run_mip.py`)

`build_pyoframe_mip.py` reuses the 17 LP equations unchanged and adds `INV = unit_size × N_UNITS` with `N_UNITS` integer for every tech in the `unit_size` table (formulation in `FORMULATION.md`). Prices come from fixing the unit counts and re-solving the LP.

```bash
python run_mip.py                                             # all new techs in whole units
python run_mip.py --integer-techs gas-cc gas-ct battery_li    # wind and solar stay continuous
python run_mip.py --regions 40 --rep-days 12 --stress-days 2 --outputs results_mip/ --highs-log mip.log
```

Checks: (1) integral units and INV = unit_size × units; (2) LP ≤ MIP bound ≤ MIP objective; (3) MIP bound ≤ fixed re-solve ≤ MIP objective; (4) the fixed-LP solution satisfies every row of the Pyomo LP with INV pinned; (5) the fixed-LP duals pass KKT on that model.

`--outputs` writes `lp/` and `mip/` folders (ReEDS-style outputs and every dual, as above), plus `mip/integer_units.csv`, `mip/eq_inv_units.csv` (value of one more MW and one more unit) and `lp_vs_mip_by_tech.csv`.

Synthetic results (HiGHS 1.15.1, 2-CPU container, `mip_rel_gap` 1e-3; LP solved with IPM):

| Case | Whole units for | Cost vs LP | MIP solve | Energy price, LP → MIP | CO2 price, LP → MIP |
|---|---|---|---|---|---|
| 2.8k rows | all new techs | +0.24% | 3 s | $59.20 → $36.58/MWh | $76.52 → $12.97/t |
| 2.8k rows | gas and batteries | +0.11% | 1 s | $59.20 → $63.51/MWh | $76.52 → $79.48/t |
| 102k rows | all new techs, warm start | +0.11% | 449 s | $63.94 → $45.40/MWh | $91.29 → $40.00/t |
| 102k rows | all new techs, no warm start | +0.12% | 694 s | $63.94 → $45.52/MWh | $91.29 → $40.00/t |
| 102k rows | gas and batteries, warm start | +0.01% | 1,016 s | $63.94 → $63.93/MWh | $91.29 → $91.14/t |
| 102k rows | gas and batteries, no warm start | +0.03% | 896 s | $63.94 → $63.76/MWh | $91.29 → $89.02/t |

The LP solves in 13–15 s at 102k rows. All five checks pass in every run.

- **MIP time is the cost.** HiGHS spends it in root-node cut rounds (about 10 s each), and every 102k run closed the gap at the root node. The warm start cut the all-tech case from 694 s to 449 s, but slowed the gas-and-battery case from 896 s to 1,016 s while reaching a tighter gap (0.009% against 0.023%). Using IPM for the relaxations was slower (0.13% gap after 709 s).
- **Prices depend on what stays continuous.** With every new tech fixed, prices fall to short-run operating cost; the $40.00/t CO2 price is exactly the coal-to-gas-CT switching cost in the synthetic data. With wind and solar continuous, prices stay close to the LP's: within 3% at 102k rows and 8% on the small case.
- **pyoframe returns 0.0 for MIP duals without an error.** `build_pyoframe_mip.results` refuses to run before the integers are fixed.

## PTDF network (`run_ptdf.py`)

`ptdf.py` swaps the zone-to-zone interface limits on AC routes for physical line limits from a DC power flow, with a reference (slack) zone you choose for each AC island. The formulation is in `FORMULATION.md`. The layer adds to any pyoframe model, including the integer-investment one.

```bash
python run_ptdf.py --ref z2                               # default lines (one per AC route), reference z2
python run_ptdf.py --lines my_lines.csv --ref z5          # your network: line,r,rr[,x,limit,limit_rev,limit_prm,limit_prm_rev]
python run_ptdf.py --lines my_lines.csv --ptdf-matrix my_ptdf.csv --ref z5   # your PTDF: line,r,value
python run_ptdf.py --case my_case --ref z2 z7             # two AC islands joined by DC ties: one reference each
python run_ptdf.py --formulation angle ...                # same network as voltage angles (sparse, faster)
```

Lines without a limit take the current interface capacity of the matching route, in each direction. Lines need not match routes; a meshed network can include lines between zones that have no route.

Checks:
1. Line flows match an independent DC power flow (B·θ = P) on the solved injections.
2. Injections sum to zero on every AC island.
3. Every flow is within its limits.
4. The same injections give the same line flows under a second reference zone, and re-solving with that reference gives the same objective.
5. The solution satisfies every row of the matching Pyomo model.
6. The duals pass KKT on that model.

`--outputs` adds `ptdf_matrix`, `ptdf_ref`, `tran_flow_line`, `tran_line_util`, `tran_line_price` (congestion price: $/MWh in representative hours, $/MW per stress timeslice) and `netinj` to the ReEDS-style outputs. It also writes every network dual, `zone_prices.csv` (transport vs PTDF), and `ptdf_matrix_full_precision.csv` in the `--ptdf-matrix` input format.

Synthetic results (all six checks pass in every case):

| Case | Network | Reference | Cost vs transport | Network LP solve | Transport LP solve |
|---|---|---|---|---|---|
| 3 zones | triangle, route capacities | z2 | +0.010% | 0.1 s | 0.1 s |
| 8 zones | ring + 3 chords from a user CSV | z6 | −0.038% (chords add paths) | 0.4 s | 0.3 s |
| 8 zones | two radial AC islands, DC ties | z2, z7 | 0.000% (radial = transport) | 0.3 s | 0.3 s |
| 40 zones, 102k rows | 40-line ring, PTDF | z20 | +0.003% | 90 s | 15 s |
| 40 zones, 102k rows | same, angle formulation | z20 | +0.003% (same objective) | 48 s | 15 s |

Changing the reference zone changes the PTDF values, not the result: flows agree to about 1e-11 MW and objectives to 1e-16. For full ReEDS (134 zones), use the angle formulation. The dense PTDF puts one term per zone in every line row, every hour.

## Next steps

1. Export the contract tables from a Pacific run on the ReEDS machine (definitions in `FORMULATION.md`), then run gates 1–4 against the GAMS slice solution.
2. Scale to WECC and USA_fast exports; record build time and memory per solve year.
3. Extensions: integer INVTRAN blocks with fix-and-resolve duals; convex quadratic losses (pyoframe via Ipopt, Pyomo via SCIP/Ipopt); MIQCP (Pyomo + SCIP; pyoframe has no open-source path today).
4. Incremental re-solve: add stress hours, as in a PRAS iteration, and re-solve without a rebuild.
