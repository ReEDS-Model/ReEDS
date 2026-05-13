# ReEDS LP Framework Comparison

Benchmarks Python LP frameworks for ReEDS.
Each framework solves the same parametric test problem at four sizes and is evaluated
on build time, solve time, peak memory, and lines of code.

## Problem structure

The test problem is a simplified single-vintage capacity-expansion LP with the same
indexing and constraint patterns as `reeds/core/setup/c_model.gms`:

| Element | Description |
|---------|-------------|
| Variables | `GEN[i,r,h,t]`, `CAP[i,r,t]`, `INV[i,r,t]`, `FLOW[r,rr,h,t]`, `RAMPUP[i,r,h,t]`, `CHARGE[i,r,h,t]`, `SOC[i,r,h,t]` |
| `eq_cap_accum` | Capacity accumulation across years |
| `eq_cap_limit` | Generation ≤ region-specific CF × capacity |
| `eq_mingen` | Minimum hourly dispatch fraction |
| `eq_supply_demand` | Energy balance with transmission and storage charging |
| `eq_reserve_margin` | Planning reserve requirement |
| `eq_transmission_limit` | Corridor flow limits |
| `eq_emit_cap` | Annual CO₂ cap |
| `eq_ramping` | RAMPUP slack ≥ hour-to-hour increase in dispatch |
| `eq_min_cf` | Minimum annual capacity factor (6%) for dispatchable techs |
| `eq_soc` / `eq_soc_cap` / `eq_charge_cap` | Battery storage state-of-charge |

**Transmission** uses a sparse mesh (ring backbone + random extra edges, ~4 corridors
per region). **VRE capacity factors** vary by region. **n\_years = 2** for all sizes,
approximately matching ReEDS's sequential-myopic solve structure.

### Problem sizes

| Size | Regions | Techs | Hours | Years | ~Variables |
|------|---------|-------|-------|-------|------------|
| small | 5 | 4 | 24 | 2 | ~15 K |
| medium | 20 | 5 | 100 | 2 | ~200 K |
| large | 60 | 7 | 400 | 2 | ~3 M |
| xlarge | 120 | 8 | 800 | 2 | ~25 M |

### Technology set (in order; sizes include the first n techs)

| Tech | Type | Has startcost | Has min\_cf |
|------|------|--------------|------------|
| gas\_cc | dispatchable | yes | yes |
| gas\_ct | dispatchable | yes | yes |
| wind | VRE | — | — |
| solar | VRE | — | — |
| coal | dispatchable | yes | yes |
| nuclear | dispatchable | yes | yes |
| battery | storage | — | — |
| geotherm | dispatchable | yes | yes |

## Frameworks

| Label in benchmark | Module | Solver |
|--------------------|--------|--------|
| `linopy` | `solve_linopy.py` | HiGHS (via linopy) |
| `pyomo` | `solve_pyomo.py` | HiGHS (via highspy) |
| `pyoptinterface` | `solve_pyoptinterface.py` | HiGHS (via pyoptinterface) |
| `arco` | `solve_arco.py` | HiGHS (via Arco Python bindings) |
| `gams_highs` | `solve_gams.py` | HiGHS (via GAMS subprocess) |
| `gams_cplex` | `solve_gams.py` | CPLEX (via GAMS subprocess) |
| `gamspy_highs` | `solve_gamspy.py` | HiGHS (via GAMSPy) |
| `gamspy_cplex` | `solve_gamspy.py` | CPLEX (via GAMSPy) |

## Running

Run the comparison as a Torc workflow from the repo root. Torc handles job
isolation, wall time, and memory measurements in its SQLite database.

```bash
uv sync --project tests/framework_comparison

torc -s --in-memory \
  --db tests/framework_comparison/torc_output/torc.db \
  run tests/framework_comparison/torc_workflow.yaml \
  --max-parallel-jobs 1 \
  -o tests/framework_comparison/torc_output
```

Change each job's `size` parameter list in `torc_workflow.yaml` to run larger
sizes. Add or edit job blocks to change framework/solver combinations; each block
passes `--label`, `--module`, and `--solver` to `run_framework.py`. Torc 0.30.1+
is required for `--in-memory` standalone runs.

Per-framework adapter JSON files are written to
`tests/framework_comparison/torc_output/framework_results/`. Torc runtime and
memory metrics are in `tests/framework_comparison/torc_output/torc.db`.

### Inspecting Torc results

```bash
tests/framework_comparison/review_torc_results.sh
```

Or pass a specific Torc database:

```bash
tests/framework_comparison/review_torc_results.sh path/to/torc.db
```

## Environment setup

Use the local `uv` project:

```bash
uv sync --project tests/framework_comparison
```

Torc must be available on `PATH`:

```bash
torc --version
```

### GAMS (solve_gams.py)

`solve_gams.py` calls GAMS via subprocess. By default it uses
`/Library/Frameworks/GAMS.framework/Resources/gams`; pass `gams_exe=` to
`solve()` or `--gams-exe` when running the script to use another installation.

### GAMSPy (solve_gamspy.py)

GAMSPy requires a license that is validated against `license.gams.com:443` on
every `Container()` call. On the NLR network (Netskope SSL inspection), two
user-level environment variables must be set:

```
CURL_CA_BUNDLE  = C:\Users\<you>\.certs\windows-root-ca-bundle.pem
CURL_SSL_NO_REVOKE = 1
```

Set these via **System Properties → Environment Variables** and restart VSCode
(or any process that calls GAMSPy) for them to take effect.

To install the GAMSPy license:

```powershell
& "C:\envs\reeds2\python.exe" -m gamspy install license <access_code>
```

## Files

| File | Purpose |
|------|---------|
| `data_generator.py` | Generates `ProblemData` for each size; single source of truth for all parameters |
| `torc_workflow.yaml` | Torc workflow defining framework/solver benchmark jobs |
| `run_framework.py` | Thin adapter called by Torc jobs; writes per-job JSON results |
| `review_torc_results.sh` | Prints Torc runtime/memory metrics and adapter result summaries |
| `solve_linopy.py` | linopy implementation |
| `solve_pyomo.py` | Pyomo implementation |
| `solve_pyoptinterface.py` | pyoptinterface implementation |
| `solve_arco.py` | Arco Python implementation (includes `uv --script` metadata) |
| `solve_gams.py` | Writes a `.gms` file and invokes GAMS via subprocess |
| `solve_gamspy.py` | GAMSPy implementation |
| `verify_env.py` | Lightweight import and solve check (older, pre-ramping/storage version) |
| `torc_output/` | Torc database, job logs, and framework result JSONs |
