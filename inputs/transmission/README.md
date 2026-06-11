# Transmission input files

- `b2b_converters.csv`: Power capacity and location of back-to-back (B2B) AC/DC/AC converters in the USA.
  - Power capacities are from [Brinkman et al. 2020](https://docs.nlr.gov/docs/fy21osti/78161.pdf) for converters at the eastern/western interface and [ERCOT 2020](https://www.ercot.com/files/docs/2020/07/30/ERCOT_DC_Tie_Operations_Document.docx) for converters at the eastern/texas interface.
  - Locations are from the [Open Infrastructure Map](https://openinframap.org/#4.1/40.65/-97.11).
  The `osm_id` column gives the OpenStreetMap ID of the converter; for example, the "Miles City, MT" converter (with `osm_id = 137835349`) can be found at <https://www.openstreetmap.org/way/137835349>.
  This file is used to validate the interface-level B2B capacity for different spatial resolutions stored at `inputs/zones/{GSw_ZoneSet}/b2b.csv`.

- `conductor_(ac|dc)*.csv`: Conductor and power rating assumptions for AC/DC transmission lines as a function of voltage from the MISO 2025 Transmission Cost Estimation Guide ([parent page](https://www.misoenergy.org/planning/transmission-planning/mtep), [description](https://cdn.misoenergy.org/MISO%20Transmission%20Cost%20Estimation%20Guide%20for%20MTEP25337433.pdf), [data workbook](https://cdn.misoenergy.org/MISO%20Transmission%20Cost%20Estimate%20Workbook%20for%20MTEP25547535.xlsx))
  - `conductor_ac_acss.csv` and `conductor_dc.csv` use the conductors specified by the MISO guide.
  AC lines use either ACSR or ACSS conductors depending on the voltage.
  - `conductor_ac_acsr.csv` instead uses ACSR for all AC voltages.
  Ampacities for 477 kcmil (Flicker) and 795 kcmil (Drake) ACSR conductors are taken from [Southwire](https://www.southwire.com/wire-cable/bare-aluminum-overhead-transmission-distribution/acsr/p/ALBARE6).

- `cost_hurdle_country.csv`: Hurdle rate for transmission flows [\$/MWh] between USA/Canada and USA/Mexico.

- `cost_hurdle_intra.csv`: Hurdle rate for transmission flows [\$/MWh] between ReEDS spatial hierarchy levels.

- `dollaryear.scv`: U.S. dollar year for cost-related input files

- `hvdc_existing.csv`: Power capacity and start/end locations of [high-voltage direct current (HVDC) lines](https://en.wikipedia.org/wiki/List_of_HVDC_projects#North_America) in the USA.
These lines are mapped to ReEDS zone interfaces during input processing.

- `hvdc_planned-*.csv`: Individual planned transmission projects
  - Files:
    - `hvdc_planned-baseline`: Included in all runs
      - TransWest Express: Planned online date and capacity from [CAISO 2026](https://www.caiso.com/documents/ceo-report-mar-2026.pdf); route from [TransWest Express](https://www.transwestexpress.net/about/maps.shtml)
      - SunZia: Planned online date from [CAISO 2026](https://www.caiso.com/documents/apr-13-2026-informational-filing-of-effective-date-transmission-control-agreement-regarding-subscriber-participating-transmission-owners-sunzia-er25-169.pdf); capacity and converter type from [Hitachi](https://www.hitachienergy.com/news-and-events/customer-stories/sunzia-transmission-enabling-3-gw-of-renewable-power-across-the-u-s-southwest); endpoints from [OpenInfraMap](https://openstreetmap.org/way/1420870282)
    - `hvdc_planned-NTP_MT`: Lines used in the "MT" scenario of the [NTP Study](https://www.energy.gov/oe/national-transmission-planning-study-0)
    - `hvdc_planned-NTP_P2P`: Lines used in the "P2P" scenario of the [NTP Study](https://www.energy.gov/oe/national-transmission-planning-study-0)
  - Columns:
    - `year_online`: If set to 0, determined from `this_year` and `years_until_trans_longterm` in `inputs/scalars.csv`
    - `trtype`: LCC or VSC (also accepts AC, but it is better to handle AC additions via the ITL calculation than to add their rated capacity directly)
    - `certain`: If 1, the line MUST be built at the provided `MW` capacity in `year_online`; if 0, the line MAY be built at up to the provided `MW` capacity starting in `year_online`

- `itl_config.yaml`: Configuration file for interface transfer limit (ITL) calculations using the [TSC](https://github.nrel.gov/ReEDS/TSC) model.
Metadata only; not used directly in ReEDS.

- `itl_NARIS.csv`: Database of initial forward/reverse AC ITLs [MW] between pairs of connected ReEDS model zones for all supported zone resolutions.
Calculated using the [TSC](https://github.nrel.gov/pbrown/TSC) model as described by [Brown et al.](https://arxiv.org/abs/2308.03612) using nodal network data from [NARIS](https://www.nlr.gov/docs/fy21osti/79224.pdf).
  - The zone identifier is the md5 hash of the ','-delimited sorted list of 5-digit FIPS codes for the counties that define the zone.
    - For example, Delaware is 3 counties, with FIPS codes 10001, 10003, and 10005.
    Its delimited string is `10001,10003,10005`, and the md5 hash of that string is `a182e260da3f30b54260bf499f0db584`.
    (If on mac you can check it on the terminal with `$ echo -n 10001,10003,10005 | md5sum`.)
    - That hash is the same whether we call the zone `DE`, `Delaware`, `p125`, or something else.
    - The hash can be determined on the fly, but to make it easier to inspect, we record it for each supported spatial resolution in the `inputs/zones/{GSw_ZoneSet}/zonehash.csv` files.
  - The `itl_NARIS.csv` is indexed by the hashes of the two zones that define the interface (`md5_from` and `md5_to`).
    - So even though the `DE` and `MD` zones are used in many of the supported region resolutions, we only store the ITL for the `DE`/`MD` interface once, with `md5_from = a182e260da3f30b54260bf499f0db584` and `md5_to = f8644441280e76e07363ed18c744f98e`.
    - The interfaces to expect values for are listed in the `inputs/zones/{GSw_ZoneSet}/interfaces_{level}.csv` files, where `level` can be `r` or `transgrp`.
  - The most straightforward way to read all the ITLs for a given region resolution is to run the following commands from the root of the ReEDS repo with the `reeds2` conda environment activated:

    ```python
    import reeds
    ## GSw_ZoneSet can be any of the supported zone resolutions listed in the `GSw_ZoneSet` row of `cases.csv`
    GSw_ZoneSet = 'z134'
    reeds.inputs.get_itls(GSw_ZoneSet=GSw_ZoneSet)
    ```

- `newlinks_offshore_backbone.csv`: Candidate connections between offshore zones
  - Similarly formatted files for candidate connections between offshore and coastal land-based zones are found at `inputs/zones/{GSw_ZoneSet}/newlinks_offshore_radial.csv`

- `transmission_cost_ac_500kv_z134.h5`: Example file illustrating the required format when using the transmission upgrade supply curve ([TSC](https://github.nrel.gov/ReEDS/TSC)) method for `GSw_ZoneSet = z134`
  - The full method is not yet supported; when implemented, it will only be supported for a limited number of `GSw_ZoneSet` definitions

- `transmission_cost_distance.csv`: Cost [USD2024] and distance [miles] for greenfield interzonal single-circuit transmission lines of the specified polarity (AC or DC) and voltage [kV] between nodes of the specified zone hashes
  - Node locations are described in `inputs/zones/README.md` and found in the `inputs/zones/{GSw_ZoneSet}/zonehash.csv` files
  - Least-cost paths between nodes (and integrated land/terrain-dependent costs along those paths) are determined using the [reV Routing (reVRt) model](https://github.com/NatLabRockies/reVRt)
  - Technical assumptions:
    - The underlying cost model is built using the MISO 2025 Transmission Cost Estimation Guide ([parent page](https://www.misoenergy.org/planning/transmission-planning/mtep), [description](https://cdn.misoenergy.org/MISO%20Transmission%20Cost%20Estimation%20Guide%20for%20MTEP25337433.pdf), [data workbook](https://cdn.misoenergy.org/MISO%20Transmission%20Cost%20Estimate%20Workbook%20for%20MTEP25547535.xlsx))
    - Costs for DC connections assume a 500 kV bipole architecture
    - Costs for AC connections use interface-dependent voltage assumptions.
    The voltage is given by the maximum voltage of an existing transmission line between the pair of zones defining the interface (using the same [NARIS](https://www.nrel.gov/docs/fy21osti/79224.pdf) dataset described above), with a floor of 138 kV.
  - The MISO Transmission Cost Estimation Guide applies a 30% length adder to the straight-line distance between the endpoints of a candidate line to account for the "squiggliness" of line routes in practice.
  Many of the least-cost routes from the reV model have a smaller squiggliness factor.
  In `reeds/input_processing/transmission.py` (which is run at the beginning of each ReEDS run),
  if the representative route between two zones has a squiggliness factor less than the user-provided `GSw_TransSquigglinessMin` switch (with a default of 1.3, matching the MISO guide),
  the cost and distance of that route are scaled up by the ratio of (`GSw_TransSquigglinessMin` / (squiggliness of the least-cost route)),
  such that every interzonal interface is represented by a line at least as squiggly as `GSw_TransSquigglinessMin`.

- `transmission_cost_distance_lines.csv`: Similar to `transmission_cost_distance.csv`, but for individual existing and planned/possible HVDC lines, with latitude/longitude for start/end points instead of zone hashes
  - Voltages are in kilovolts [kV]
  - Costs and lengths (and underlying routes, not included in the file) are from the [reV Routing (reVRt) model](https://github.com/NatLabRockies/reVRt) and are not expected to exactly match the actual costs, lengths, or routes of existing lines
