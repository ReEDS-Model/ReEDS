# Consume input files

- `consume_char_*.csv`: Cost (capex, FOM, VOM) and efficiency (gas and electrical) as well as storage and transmission adder (`stortran_adder`) inputs for various H2 producing technologies. Units vary by parameter; refer to [b_inputs.gms](https://github.com/ReEDS-Model/ReEDS/blob/main/reeds/core/setup/b_inputs.gms)
  - `consume_char_low.csv`: Conservative assumptions
  - `consume_char_ref.csv`: Reference assumptions

- `dac_elec_BVRE_2021_*.csv`: DAC costs (capex [$/(metric ton CO2/hr)], FOM [$/(metric ton CO2/hr)/yr], VOM [$/metric ton CO2]) and conversion rate, over time.
  - `dac_elec_BVRE_2021_high.csv`: High assumptions
  - `dac_elec_BVRE_2021_low.csv`: Low assumptions
  - `dac_elec_BVRE_2021_mid.csv`: Mid assumptions
  - Citation: `REF-DAC-VALENTINE-2022`

- `dac_gas_BVRE_2021_*.csv`: DAC costs (capex [$/(metric ton CO2/hr)], FOM [$/(metric ton CO2/hr)/yr], VOM [$/metric ton CO2]) and conversion rate, over time.
  - `dac_gas_BVRE_2021_high.csv`: High assumptions
  - `dac_gas_BVRE_2021_low.csv`: Low assumptions
  - `dac_gas_BVRE_2021_mid.csv`: Mid assumptions
  - Citation: `REF-DAC-VALENTINE-2022`

- `dollaryear.csv`: Dollar year for various Beyond VRE scenarios

- `h2_demand_county_share.csv`: The fraction of national hydrogen demand in that year that corresponds to each county
  - Demand estimates come from https://data.openei.org/submissions/5655
  - 2021 demand shares correspond to the "Reference" scenario with light-duty vehicles / biofuels / methanol demand removed and 2050 shares correspond to the "Low Cost Electrolysis" scenario

- `h2_exogenous_demand.csv`: Exogenous hydrogen demand by industries other than the power sector per year

- `h2_transport_and_storage_costs.csv`: Transport and storage costs of hydrogen per year (in $2004)


## References
- `REF-DAC-VALENTINE-2022`: J. Valentine and A. Zoelle, "Direct Air Capture Case Studies: Sorbent System," National Energy Technology Laboratory, Pittsburgh, PA, July 8, 2022. https://doi.org/10.2172/1879535
