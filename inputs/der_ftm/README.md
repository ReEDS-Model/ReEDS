## Front-of-the-Meter Distributed Energy Resource (FTM DER) Input Files

FTM DER are distribution-connected resources that ReEDS can invest in when `GSw_DER_FTM = 1`.
There are three technologies:

- **`der-ftm-pv`**: PV with a fixed profile. The profile is a copy of the distpv profile (including the
  scaling by `1/(1-distloss)` that converts distribution-level generation to busbar generation),
  and the RPS/CES treatment of distribution losses is the same as for distpv.
  Like other new PV, new FTM PV vintages also get the PV capacity factor improvement (`pv_cf_improve`).
  Unlike distpv, FTM PV generation does not reduce the end-use sales used for RPS requirements.
- **`der-ftm-battery_li`**: standalone battery storage that cannot charge in the hours given by the no-charge profile below
  in zones and years with prescribed FTM battery builds (starting in the first year with a prescribed build);
  the restriction then applies to all FTM battery capacity in the zone, including optional builds.
  Like utility-scale batteries (`battery_li`), ReEDS chooses both its power capacity [MW] and its energy capacity [MWh]
  (subject to the minimum battery duration `minbatteryduration` in `inputs/scalars.csv`).
  It is in the `BATTERY` tech subset, so it counts toward state battery mandates, but it is excluded from the
  `battery` tech group used for tech-group constraints.
  Because it is connected to the distribution system, its charging is treated like end-use load: 1 MW of charging
  adds `1/(1-distloss)` MW of busbar load, and 1 MW of discharge displaces `1/(1-distloss)` MW of busbar load
  (`busbar_mult_storage` in `b_inputs.gms`). The round-trip efficiency applies at the battery itself.
  The same scaling applies to the operating reserves it provides (1 MW of reserves at the device meets
  `1/(1-distloss)` MW of the busbar-level requirement) and to resource adequacy: PRAS sees its power and
  energy capacity scaled up by `1/(1-distloss)` (`resource_adequacy/prep_data.py`).
  Charging from FTM PV is not modeled separately: since FTM PV output is already credited with avoided distribution
  losses, charging from it costs the same `1/(1-distloss)` MW of busbar supply per MW as charging from the bulk grid.
- **`der-ftm-shape`**: a change to the load shape, like the `dr_shape` technologies. It does not generate.
  Each MW of capacity changes end-use load by the load shape profile (MW per MW of capacity; negative values are
  load reductions; see the files below). Because the profile is at the end-use level, the
  change to busbar load is scaled up by `1/(1-distloss)`, like end-use load (`eq_loadcon` in `c_model.gms`).
  It provides no operating reserves and no firm capacity in the capacity credit formulation of the planning
  reserve margin; its effect on resource adequacy comes through the load in stress periods and in PRAS
  (`resource_adequacy/prep_data.py`). It is in the `DER_FTM_SHAPE` tech subset.

In hours given by the minimum-output profile below, the combined net output of the FTM PV and battery technologies
in a zone (PV generation plus battery discharge minus battery charging, measured at the devices rather than the busbar)
must be at least a given number of MW.
This requirement applies only in zones and model years where prescribed FTM PV or battery builds exist,
but output from all FTM PV and battery capacity (prescribed and optional) counts toward it.
`der-ftm-shape` neither counts toward this requirement nor triggers it.

### Costs

FTM DER use the costs and performance of the corresponding utility-scale technologies
(`reeds/input_processing/plantcostprep.py`):

- `der-ftm-pv` takes its capital cost, fixed O&M, and variable O&M from utility-scale PV (`plantchar_upv`),
  in $/kW-DC like UPV.
- `der-ftm-battery_li` takes its power and energy capital costs, fixed O&M, variable O&M, and round-trip efficiency
  from `battery_li` (`plantchar_battery`), including the battery refurbishment adder on the energy capital cost.
- `der-ftm-shape` has no utility-scale counterpart: it has no base capital cost and no O&M costs, so its
  supply curve cost (below) is its full capital cost. Its financing inputs are under the `DER_FTM_SHAPE` tech group
  in `inputs/financials` (the same as `DR_SHAPE`, but with a 30-year evaluation period, or 20 years in the CRP20 file).

On top of the utility-scale capital cost (zero for `der-ftm-shape`), each FTM DER technology pays a supply curve
cost adder [$/MW] that depends on the bin and the build year. The example supply curve has three bins:

1. **bin1**: prescribed builds. ReEDS must build the capacity in `der_ftm_prescribed_{der_ftm_scen}.csv`
   in each year. The capacity of bin1 in year t is the cumulative prescribed capacity through t,
   so optional builds cannot use it.
2. **bin2** and **bin3**: optional capacity. ReEDS decides whether to build in these bins.
   Their capacity in year t is the cumulative capacity that can be built from the bin through t.

Prescribed builds are assigned to bin1 because it is the cheapest bin, so costs must not decrease
from bin1 to bin2 to bin3 in any year (input processing checks this).
Investment in year t pays the bin's adder in year t (plus the financing multiplier, `rsc_fin_mult`, which is the same
as for the utility-scale capital cost).
The adder applies to power capacity only; battery energy capacity pays the `battery_li` energy capital cost.
Prescribed battery energy capacity (`MWh` in the prescribed builds file) is a minimum:
ReEDS must build at least that much energy capacity in each year with prescribed builds and can build more
(on prescribed or optional power capacity) at the energy capital cost.

Capacity and costs are by ReEDS zone (`r`); aggregated or county-level spatial resolutions are not supported yet.
All files are included in the repository; `example` contains illustrative (not real) data for the
Pacific census division zones only.

### Files (`{der_ftm_scen}` is set by the `der_ftm_scen` switch)

- **`der_ftm_prescribed_{der_ftm_scen}.csv`**: Prescribed (bin1) builds by tech (`i`), zone (`r`), and build year (`t`).
  Columns: `i,r,t,MW,MWh`. `MW` is power capacity (MW-DC for PV); `MWh` is battery energy capacity and should be blank for
  non-battery techs. `MWh` can only be given in rows with `MW > 0`.
- **`der_ftm_supplycurve_{der_ftm_scen}.csv`**: Supply curve by tech (`i`), zone (`r`), bin (`rscbin`), and year (`t`).
  Columns: `i,r,rscbin,t,cap,cost`.
  - `cap` [MW; MW-DC for PV] is the cumulative capacity available in the bin through year `t`; it cannot decrease over time.
    It must be blank for bin1 (it is set to the cumulative prescribed capacity).
  - `cost` is the capital cost adder [$/MW; $/MW-DC for PV] for builds in year `t`, in the dollar year listed for
    `der_ftm_{der_ftm_scen}` in `inputs/supply_curve/dollaryear.csv`. It can be zero or negative.
    For `der-ftm-shape` it is the full capital cost.
  - Values are filled forward from each `t` until the next `t` in the file; bins are unavailable before their first `t`.
    Every zone with prescribed builds needs a bin1 cost in or before its first year with prescribed builds.
- **`der_ftm_min_output_{der_ftm_scen}.h5`**: Minimum combined net output [MW] of the FTM PV and battery technologies
  in each zone (generation minus battery charging).
  Index: (`year`, `hour`), where `year` is the model year and `hour` is the hour of the year (1–8760, Central Standard Time);
  columns are zones. The same profile is used for every weather year.
- **`der_ftm_battery_nocharge_{der_ftm_scen}.h5`**: 1 in hours when FTM batteries cannot charge, 0 otherwise.
  Only used in zones and years with prescribed FTM battery builds.
  Same format as the minimum-output file.
- **`der_ftm_profile_change_{der_ftm_scen}.h5`**: Change in end-use load per MW of `der-ftm-shape` capacity [MW/MW];
  positive values are load increases and negative values are load reductions.
  The change in end-use load is this profile × capacity. Same format as the minimum-output file.

For all profiles, each model year uses the data for the latest `year` at or before it
(or the earliest `year` if all are after it). When modeled timeslices aggregate several hours,
the profiles are averaged over the hours in the timeslice
(so a timeslice in which charging is restricted for half of the hours allows charging at up to half of the power capacity).

Make sure the minimum output can be met by the prescribed FTM DER capacity, given the PV profile, battery energy capacity,
and hours when charging is allowed; otherwise the model must build optional FTM DER capacity to meet it, or is infeasible
if the supply curve does not have enough capacity.
