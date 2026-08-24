# ReEDS integration status

The Puerto Rico explicit-region adapter is implemented in this ReEDS checkout. It is activated only when `GSw_ZoneSet=PR_explicit`; existing CONUS spatial modes retain their normal behavior.

## Implemented path

The adapter uses the 121 connected buses at or above 115 kV as authoritative ReEDS regions. `prepare_pr_explicit_zone.py` writes the hierarchy and compatibility tables under `inputs/zones/PR_explicit`. These tables satisfy legacy geographic interfaces without using municipality or county boundaries to relocate electrical data.

`prepare_pr_reeds_inputs.py` registers the native spatial inputs:

- PR100 UPV, onshore-wind, and offshore-wind supply curves
- 2018–2019 site-level renewable capacity-factor profiles
- the `PR-115plus` integration-test generator database
- regional load, distributed PV, distributed storage, and Tranche 1 solar
- fixed directional transmission interfaces derived from the staged ITLs

`prepare_pr100_mirror.py` then registers the calibrated `PR100-1LM` unit
database and case-specific inputs. These include the public annual DPV totals,
PR100 renewable-policy schedule, PR100-shaped annual renewable and battery
costs, official aggregate fleet/retirement and storage prescriptions,
fuel-specific price trajectories, report-method transmission ratings/losses,
and the official 1LM capacity benchmark used after the solve.

Guarded changes under `reeds/` then:

- accept already-regional supply curves and load;
- avoid CONUS county remapping and remote-data synchronization;
- process the explicit-region unit database directly;
- use Puerto Rico transmission distances and capacities;
- use a one-hot South Atlantic census-division proxy for provisional gas inputs;
- normalize PR100 AST load into the ReEDS chronological time zone;
- bypass polygon-only map generation for point nodes; and
- emit harmless nonempty defaults where a disabled feature still has a required GAMS input domain.

Transmission expansion is disabled. The dummy spur site used by the compatibility path has zero cost and cannot become an investment option while `GSw_SpurScen=0`.

## Verified boundary

The following steps have completed successfully in a generated case directory:

1. all Python input-processing scripts;
2. representative/stress-period construction;
3. HDF5-to-GDX conversion;
4. GAMS model creation and restart generation; and
5. first-year model compilation and LP generation.

The generated smoke-case 2010 LP has 50,719 rows, 59,061 columns, and 208,317
nonzeros. The PR100 mirror also passed the complete input/GDX/GAMS build and
generated a 2010 LP with 43,512 rows, 51,742 columns, and 168,239 nonzeros. The current GAMS
installation cannot solve either full model because CPLEX is limited to
demo-sized models and HiGHS is not included in the installed license. A
licensed solver is therefore still required to establish feasibility and
optimality.

## Remaining source limitations

The earlier smoke case retains provisional assumptions. The `PR100_1LM_mirror`
column replaces most of them, but the following cannot be matched exactly from
the public release:

- proprietary Engage/LUMA unit-level fleet, heat-rate, and PPOA workbooks;
- exact source fuel-price spreadsheet values (public report curves are digitized);
- nodal rooftop-PV profiles;
- year-varying ReEDS resource geometry (one 2035 geometry is used with annual costs);
- later-than-2035 public onshore/offshore cost curves; and
- PR100 event-level outage draws for PRAS.

The comparison case is `PR100_1LM_mirror` in `cases_pr.csv`; the earlier
`PR_115plus_input` column remains available as an integration smoke case. Both
have `input_processing_only=0`, so a licensed environment proceeds through the
full model rather than stopping after input generation.
