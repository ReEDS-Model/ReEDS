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

All commands assume the `reeds_benchmark` conda environment and are run from the repo root
or from `tests/framework_comparison/`.

```powershell
# Activate environment
conda activate reeds_benchmark

# Quick sanity check — all frameworks, small problem only
python tests/framework_comparison/benchmark.py --size small

# Full benchmark — all sizes (slow, large takes ~5 min per framework)
python tests/framework_comparison/benchmark.py

# Subset of frameworks or sizes
python tests/framework_comparison/benchmark.py --frameworks linopy pyomo --size small medium

# GAMSPy with CPLEX only
python tests/framework_comparison/benchmark.py --frameworks gamspy_cplex --size small medium large
```

Results are printed to the terminal and saved as CSV in `results/`.

### Running Arco standalone with `uv --script`

`solve_arco.py` includes inline `uv` metadata and pins Arco to the current PR commit. You can compile/install the bindings directly from that source with:

```bash
uv run --script tests/framework_comparison/solve_arco.py
```

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--size` | all | Problem size(s): `small medium large xlarge` |
| `--frameworks` | all | Framework labels (see table above) |
| `--repeat N` | 1 | Repeat each run N times; report minimum times |
| `--no-memory` | off | Skip peak RSS measurement |

## Environment setup

### Conda environment

Create and activate the dedicated benchmark environment from the pinned spec:

```powershell
conda env create -f tests/framework_comparison/environment.yml
conda activate reeds_benchmark
```

The environment installs: `linopy`, `pyomo`, `highspy`, `highsbox`,
`pyoptinterface`, `gamspy`, `gamspy_base`, `psutil`, `numpy`, `xarray`.
`highsbox` provides the HiGHS shared library required by pyoptinterface.

### GAMS (solve_gams.py)

`solve_gams.py` calls `gams.exe` via subprocess. The GAMS executable path is
hard-coded at the top of that file; update it if your GAMS installation is elsewhere.

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
& "C:\envs\reeds_benchmark\python.exe" -m gamspy install license <access_code>
```

## Files

| File | Purpose |
|------|---------|
| `data_generator.py` | Generates `ProblemData` for each size; single source of truth for all parameters |
| `benchmark.py` | Main harness: runs frameworks, measures time/memory, saves CSV |
| `solve_linopy.py` | linopy implementation |
| `solve_pyomo.py` | Pyomo implementation |
| `solve_pyoptinterface.py` | pyoptinterface implementation |
| `solve_arco.py` | Arco Python implementation (includes `uv --script` metadata) |
| `solve_gams.py` | Writes a `.gms` file and invokes GAMS via subprocess |
| `solve_gamspy.py` | GAMSPy implementation |
| `verify_env.py` | Lightweight import and solve check (older, pre-ramping/storage version) |
| `results/` | Benchmark output CSVs, timestamped |
