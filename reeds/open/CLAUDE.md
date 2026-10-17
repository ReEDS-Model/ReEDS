# CLAUDE.md: working rules for this repository

Read `README.md` first (context, status, decisions, next steps). The math is in `FORMULATION.md`.

## Commands

```bash
pip install -r requirements.txt
pytest -q                                          # must pass before and after every change (~30 s)
python run_bakeoff.py --highs-solver ipm           # LP gates 1-4 (pyoframe vs Pyomo)
python run_mip.py                                  # integer investment, checks 1-5
python run_ptdf.py --ref z2 [--formulation angle]  # network layer, checks 1-6
# scale: --regions 40 --rep-days 12 --stress-days 2  (~102k rows; LP ~15 s, MIP 7-17 min, PTDF 48-90 s)
```

A runner returns non-zero, or prints FAIL, when a check fails. Treat that as a broken model, not as noise.

## Architecture rules

- **Data → prep → builders → layers.**
    - `contract.py` defines the input tables.
    - `prep.py` turns them into domains (`P.var`, `P.con`) and coefficient tables (`P.coef`, `P.obj`).
    - Builders contain algebra only. Never filter or compute coefficients inside a builder; add a table in `prep.py` instead.
- **Every equation exists twice:** in `build_pyoframe.py` and in `build_pyomo.py` (or in the layer's `add_pyoframe` and `add_pyomo`). Pyomo is the checking oracle for `run_bakeoff.cross_check` and `kkt.check`. A new equation without its Pyomo twin cannot be verified.
- **Layers never edit the 17 LP equations.** `build_pyoframe_mip.py` and `ptdf.py` add variables and equations after `build_pyoframe.build`. The one sanctioned change is `ptdf.prepare` shrinking `P.con["eq_transmission_limit"]` to non-AC routes.
- **Checks need the layer's names in P.** Use `ptdf.with_layer(P, layer)` to give checks and reports the extra variables and equations. Never pass that extended P to `build_pyoframe.build`: it would create the layer variables with `lb=0`.

## Invariants (tests depend on them)

- **Orientation.** Write every constraint as (GAMS LHS) − (GAMS RHS) {≥, =, ≤} 0, so duals carry the GAMS marginal sign. `kkt.check` assumes minimization with y ≥ 0 on ≥ rows and y ≤ 0 on ≤ rows.
- **GAMS zero semantics.** `contract.normalize` drops zero parameters. A row exists even when its constant is zero; materialize such constants with `_on_domain(..., fill 0)` in prep.
- **Determinism.** `prep._sorted` sorts every table. Keep new tables sorted, or degenerate LPs will land on different vertices from run to run.
- **Column order.** Index columns follow GAMS order: GEN(i,v,r,h,t), FLOW(r,rr,h,t,trtype). Years are `pl.Int64`; every other index is `pl.Utf8`.

## Known pitfalls (each one cost time already)

- **pyoframe returns 0.0 for duals after a MIP solve, with no error.** Only read duals after `build_pyoframe_mip.fix_integers` and `resolve_fixed`; `results()` enforces this.
- **pyoframe `Model.convert_to_fixed()` is Gurobi-only.** For HiGHS, fixing works through `m.poi.set_variable_attribute`: Domain → Continuous, then LowerBound = UpperBound = value.
- **The MIP gap from pyoptinterface is wrong.** `ModelAttribute.RelativeGap` returns the `mip_rel_gap` option, not the gap reached. Read `m.poi.get_raw_info_double("mip_gap")` and `"mip_dual_bound"`.
- **pyoframe models reject extra attributes.** Keep state in a wrapper; see `MIPModel`.
- **pyoframe stores constants as a fixed column.** HiGHS therefore reports RHS ranges as zero and lists constants (for example the 1.15e8 t CO2 cap) under the matrix range. Presolve removes the column; it is not a numerical problem.
- **pyoframe joins are strict.** Adding expressions with different label sets raises an error. Use `keep_extras()` (union; missing = 0), `drop_extras()` (a `$` filter) or the `U(...)` helper in `build_pyoframe.py`.
- **polars `fill_null(0.0)` on a whole frame turns Int64 year columns into Float64.** Fill only the value columns.
- **polars treats a `"*"` column name as a wildcard.** `report.py` carries GAMS `*` domains as `_s0/_s1/_s2` and renames them at write time (`*`, `*.1`, `*.2`, as `reeds.io` does).
- **HiGHS is not found automatically.** pyoptinterface does not find the HiGHS library in the highspy wheel; call `solvers.load_highs()` first. The runners and tests do.
- **Pyomo HiGHS runs are not reproducible.** Both interfaces (appsi and `pyomo.contrib.solver`) order columns differently each run. Compare Pyomo duals with KKT, never row by row.
- **Stress timeslices have `hours = 0`,** as in ReEDS. Prices for stress hours are $/MW per timeslice (`res_marg`), not $/MWh.
- **`nexth` wraps within each representative day.** Use the table, not pyoframe's `.next(..., wrap_around=True)`.
- **PTDF needs one reference zone per AC island,** and every AC route must stay inside one island (make cross-island routes DC). It is incompatible with transmission investment.
- **Don't `pkill -f` a pattern that appears in your own shell command.** It kills the calling shell; kill by PID.

## Where results and references are

- Per-constraint GAMS / pyoframe / Pyomo comparison: `docs/per_constraint_comparison.md`
- Verbatim ReEDS GAMS for each equation: `docs/gams_reference/` (ReEDS-Model/ReEDS commit `ea3bcbf`)
- Previous outputs (ReEDS layout, duals, logs): `results/`
- Build-time benchmarks: `benchmarks/` (raw medians in `benchmarks/results/per_constraint_timing.json`)

## Open decision

For the Kron-reduction tool (next step 3 in README): drop equivalent lines between zones that have no ReEDS interface (recommended; the ITL then applies to exactly the interface flow), or keep them with no limit. Ask the user before building.
