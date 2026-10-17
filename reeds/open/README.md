# reeds-slice: prototype for replacing the ReEDS GAMS model with open-source Python

This project tests whether ReEDS, the capacity-expansion model of NLR (the National Laboratory of the Rockies), can move its optimization from GAMS to an open-source modeling language and open-source solvers, with room for integer and quadratic constraints later.

It implements a 17-equation slice of the ReEDS LP twice, in **pyoframe** and **Pyomo**, on one shared data layer, and proves both build the same model. On top of the pyoframe version it adds integer plant investment and a PTDF / DC power-flow network with a user-chosen reference zone.

Everything here runs on synthetic, ReEDS-shaped data. Numerical validation against GAMS on a real ReEDS case has **not** been done yet; that is the first next step.

Status as of 7 Oct 2026:

| Component | State | Verified by |
|---|---|---|
| LP slice, pyoframe and Pyomo (`run_bakeoff.py`) | Done | 4 gates at 2.8k and 102k rows: structure, objective (1e-9), cross-feasibility, KKT |
| ReEDS-style outputs and every dual (`--outputs`) | Done | Read back with ReEDS's own `read_h5`; tools agree on all non-degenerate outputs |
| Integer plant investment, pyoframe (`run_mip.py`) | Done | 5 checks at 2.8k and 102k rows |
| PTDF / angle network with user reference zone (`run_ptdf.py`) | Done | 6 checks on 3-, 8- and 40-zone networks, one and two AC islands |
| Smoke tests (`tests/`) | Done | `pytest -q`: 10 tests, about 30 s |
| GAMS export and validation on a ReEDS case | **Not started** | Needs the ReEDS machine; spec in `FORMULATION.md` |
| Kron reduction of a nodal network, ITLs as limits | Designed, not built | One decision open (see Next steps) |
| Planning-subregion ITL flowgates (`eq_transgrp_limit_energy`) | Not built | |
| Quadratic constraints (losses), MIQCP | Not started | |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                                   # 10 smoke tests, ~30 s
python run_bakeoff.py --highs-solver ipm    # LP: pyoframe vs Pyomo, gates 1-4
python run_mip.py                           # integer plant investment, checks 1-5
python run_ptdf.py --ref z2                 # PTDF network, reference zone z2, checks 1-6
```

Each runner takes `--regions N --rep-days D --stress-days S` to scale the synthetic case (40 / 12 / 2 gives about 102k rows), `--case DIR` for exported contract tables, and `--outputs DIR` to write ReEDS-style outputs and every dual. Run any of them with `-h` for all options. The full run guide and every result table are in `docs/USAGE_AND_RESULTS.md`.

## Background and decisions

1. **ReEDS structure.** Analysed at the active repository, https://github.com/ReEDS-Model/ReEDS (NREL/ReEDS-2.0 is archived), commit `ea3bcbf`.
    - Python preprocessing writes `inputs.h5`, which is converted to GDX.
    - `b_inputs.gms` (5.6k lines) derives sets and parameters; `c_model.gms` (4k lines) holds 160 equations and 85 variable families.
    - The LP is solved one year at a time (sequential mode), iterating with PRAS each year. Past years are fixed with `.fx` and restart files.
    - Reporting reads 32 duals. Solver settings are tuned for CPLEX barrier.
2. **Language choice.** JuMP, Pyomo, linopy, pyoframe and GAMSPy were compared. The decision was Python-only, with a bake-off between pyoframe and Pyomo.
    - **Result:** pyoframe for the main work. It takes 49 lines against 128 for the 17 constraints, builds 9× faster at 378k rows (4.1 s against 37 s), and gives the same solution every run.
    - **Pyomo's role:** it stays as the checking implementation, and it is the open-source route to MIQCP later (with SCIP). pyoframe 1.9.1 has no open-source solver that handles integers and quadratic constraints together; HiGHS 1.15.1 handles LP, MIP and convex QP, but not MIQP or quadratic constraints.
3. **Slice method.**
    - 17 ReEDS equations plus an objective in the ReEDS style, transcribed under a fixed switch profile.
    - Pure parameter algebra (for example the availability factor κ) is computed in GAMS at export, so the Python code tests the language, not a data port.
    - The data contract (`reeds_slice/contract.py`) lists every table the slice reads.
4. **Integer investment.**
    - `INV = unit_size × N_UNITS`, with `N_UNITS` integer, for techs listed in `unit_size`.
    - Prices come from fixing the integers and re-solving the LP.
    - The MIP starts from the LP plan rounded up to whole units.
5. **Network.**
    - PTDF from a user line list or a user PTDF matrix, with one user-chosen reference zone per AC island.
    - Line limits default to the ReEDS route capacity, which is the ReEDS interface transfer limit (ITL), in each direction.
    - The angle formulation gives identical flows and is sparse; use it at scale.
6. **Kron reduction (discussed, not built).** Kron-reduce a nodal network to one bus per zone, use the equivalent reactances with the angle formulation, and keep the ReEDS ITLs as limits.

The per-constraint comparison of GAMS, pyoframe and Pyomo is in `docs/per_constraint_comparison.md`, exported from https://claude.ai/code/artifact/c66f0283-965f-4993-b76f-43e8c9966fca.

## Layout

```
README.md                    this file: context, status, decisions, next steps
CLAUDE.md                    working rules for a coding agent (conventions, pitfalls, commands)
FORMULATION.md               the math: switch profile, domains, all equations (1-22), GAMS export definitions
requirements.txt             pinned versions every result was produced with
run_bakeoff.py               LP slice in pyoframe and Pyomo; gates 1-4; --outputs writes ReEDS outputs and duals
run_mip.py                   LP vs integer-investment MIP; fix-and-resolve prices; checks 1-5
run_ptdf.py                  transport model vs PTDF/angle network; checks 1-6
reeds_slice/
  contract.py                data contract: every input table, dtypes, GAMS zero semantics, checks
  synthetic.py               ReEDS-shaped synthetic case in the contract format (unit sizes, PTDF lines too)
  prep.py                    shared polars layer: variable/constraint domains and coefficient tables (sorted)
  build_pyoframe.py          the 17 equations + objective in pyoframe (algebra only)
  build_pyomo.py             the same in Pyomo ("fast Pyomo": dict pre-indexing + rules)
  build_pyoframe_mip.py      integer layer: N_UNITS, eq_inv_units, warm start, fix-and-resolve
  ptdf.py                    network layer: PTDF and angle formulations, islands, references; pyoframe + Pyomo
  kkt.py                     KKT optimality check of any (primal, dual) pair on the Pyomo model
  report.py                  36 ReEDS-style outputs (report.gms / report_calcs.py definitions), outputs.h5 writer
  duals.py                   every equation's Level/Lower/Upper/Marginal/Slack (GAMS results.gdx layout)
  solvers.py                 points pyoptinterface at the HiGHS library inside the highspy wheel
tests/test_smoke.py          10 smoke tests (all runners, PTDF textbook case, reference validation, MIP dual guard)
benchmarks/                  per-constraint build timing (pyoframe, Pyomo) and Pyomo handoff timing
docs/
  USAGE_AND_RESULTS.md       detailed run guide and every result table
  per_constraint_comparison.md   GAMS vs pyoframe vs Pyomo, all 17 constraints + objective, with metrics
  gams_reference/            verbatim ReEDS GAMS for each slice equation and the objective
examples/
  lines_8zone_meshed.csv     user-defined network: ring plus 3 chords (run_ptdf.py --regions 8 --lines ...)
  case_2_islands/            contract tables for two AC islands joined by DC ties (run_ptdf.py --case ...)
results/
  lp_bakeoff_synthetic/      2.8k-row outputs and duals for both tools; dual and output comparisons at 102k
  mip/                       102k-row MIP runs (all techs; gas + batteries): outputs, duals, unit counts, HiGHS logs
  ptdf/                      8-zone user network, two-island case, 40-zone 102k-row run (outputs, duals, PTDF)
```

## How the code fits together

```
contract tables (parquet or synthetic)
   └─ prep.prepare(case)            domains + coefficient tables, sorted   ─┐
        ├─ build_pyoframe.build(P)  17 equations + objective (pyoframe)     │ same P for all builders
        │    ├─ build_pyoframe_mip   + N_UNITS, eq_inv_units (integer)       │
        │    └─ ptdf.add_pyoframe    + NETINJ, LINEFLOW (+THETA), limits     │
        └─ build_pyomo.build(P)     same model in Pyomo (+ ptdf.add_pyomo)  ─┘
solve (HiGHS) → results {objective, primal, dual}
   ├─ kkt.check / cross_check       verify on the Pyomo model
   ├─ report.reeds_outputs          ReEDS-style outputs → outputs.h5 + CSV
   └─ duals.equation_tables         every row's dual, GAMS layout
```

Layers (`build_pyoframe_mip`, `ptdf`) add variables and equations to an already built LP and leave the 17 equations untouched, so the LP, the MIP and the network model cannot drift apart. They can be combined: build the MIP, then add the PTDF layer.

## Verified results (synthetic; details in `docs/USAGE_AND_RESULTS.md`)

**LP: pyoframe vs Pyomo.**
- Objectives match to 4e-10; each tool's solution satisfies the other's model; both pass KKT.
- Build time:

| Rows | pyoframe build | Pyomo build (construction + handoff to HiGHS) |
|---|---|---|
| 102k | 0.9–1.3 s | 7.4 s |
| 378k | 4.1 s | 37 s (8.2 + 29) |

- Duals are identical on 7 of 17 equations. On the other 10 they differ only on degenerate rows, and both tools' duals pass KKT.

**Integer investment, 102k rows:**

| Built in whole units | Cost vs LP | MIP solve | LP solve |
|---|---|---|---|
| All new techs | +0.11% | 449 s | 15 s |
| Gas and batteries only | +0.01% | 1,016 s | 15 s |

With every new tech fixed, prices fall to operating cost: energy $64 → $45/MWh, CO2 $91 → $40/t. With wind and solar left continuous, prices stay at LP levels.

**PTDF network:**
- 102k rows, 40-zone ring: cost +0.003%. PTDF solve 90 s, angle solve 48 s (same objective), transport solve 15 s.
- Changing the reference zone changes flows by about 1e-11 MW and the objective by about 1e-16.

## Conventions that must hold (also in `CLAUDE.md`)

- **Constraint orientation.** Each constraint is written as (GAMS left side) − (GAMS right side) {≥, =, ≤} 0, so every dual carries the GAMS marginal sign.
- **GAMS zero semantics.** The loader drops zero parameters. A missing coefficient removes a term, but the row still exists.
- **Builders hold algebra only.** Domains, filters and coefficients belong in `prep.py` (or the layer's `prepare`). Every table is sorted, which is what makes pyoframe deterministic.
- **New equations come in pairs.** Add every equation to both builders and extend the checks. The Pyomo version is the test oracle (cross-check and KKT).

## Known gaps and issues

- **Not validated against GAMS.** All results are pyoframe vs Pyomo on synthetic data.
- **Gas fuel cost is missing an hourly factor.** The slice prices gas at `heat_rate × fuel_price` without ReEDS's hourly regional multiplier `gasprice_adj_r(r,h)` (applies under `GSw_GasCurve = 2`). Fix it in the export before comparing with GAMS.
- **Pyomo is not reproducible run to run.** Its HiGHS interfaces order columns differently each run, so degenerate duals and hourly dispatch change; the KKT check still passes. The LP-file route with `file_determinism` is untested.
- **Pyomo's handoff is slow.** Passing rows to HiGHS takes 29 s at 378k rows, the same with both of its interfaces.
- **The MIP is slow with HiGHS.** It takes 449–1,016 s at 102k rows against 15 s for the LP. Using IPM inside the MIP was slower. At full scale, limit integers to a few techs or use Gurobi (pyoframe supports it).
- **The dense PTDF scales badly.** Each line row has one term per zone in the island; use `--formulation angle` for full ReEDS. PTDF mode also rejects transmission investment.
- **pyoframe pitfalls:** see `CLAUDE.md` (MIP duals return 0.0 silently, `RelativeGap` returns the option value, constants stored as matrix coefficients).
- **Much of ReEDS is outside the slice:** mingen, ramping, reserves, RPS/CES, hydro budgets, growth limits, the capacity-credit PRM, H2, DAC, water, upgrades, retirements, multi-year and window modes, and the PRAS loop. See `FORMULATION.md`, "What the slice leaves out".

## Next steps (in order)

1. **Validate against GAMS on the ReEDS machine.**
    - Write `slice_solve.gms` for a Pacific case: restrict the model to the slice equations, set `holdfixed = 1`, and use CPLEX barrier with crossover.
    - Export the contract tables (definitions in `FORMULATION.md`, "Precomposed coefficients") and the GAMS solution, including marginals.
    - Run `run_bakeoff.py --case`, and apply the KKT gate to the GAMS marginals.
    - First add the gas price multiplier (see Known gaps).
2. **Scale up** to WECC and USA_fast exports. Record build time and memory per solve year.
3. **Kron reduction + ITLs.** Build `kron.py`: bus network + bus-to-zone map + load participation factors → equivalent lines on ReEDS interfaces (for `--formulation angle`), with ITLs as the default limits, plus a report of the error from dropping other lines. **Open decision:** drop equivalent lines between zones that have no ReEDS interface (recommended) or keep them with no limit.
4. **Flowgates** for planning-subregion ITLs (`eq_transgrp_limit_energy`): a signed sum of interface flows ≤ group ITL, added in `ptdf.py`.
5. **Pyomo LP-file route:** test whether it removes the 29 s handoff and the run-to-run variation.
6. **Extensions:** integer transmission blocks with fix-and-resolve prices; convex quadratic losses (pyoframe via Ipopt, Pyomo via SCIP or Ipopt); MIQCP (Pyomo + SCIP).
7. **Incremental re-solve:** add stress hours, as in a PRAS iteration, without rebuilding the model.

## Environment

Tested on Linux (2-CPU, 8 GB cloud container; earlier runs on 1 CPU, 4 GB) with Python 3.12 and 3.13. Package versions are pinned in `requirements.txt`: pyoframe 1.9.1, Pyomo 6.10.1, HiGHS 1.15.1 (highspy). Timings in this repository come from those machines and will differ elsewhere.
