## Growth Constraints Input Files

- `gbin_min.csv`: Minimum size of the first (zero cost) growth bin [MW] by technology group
  - Based on the representative plant size for a single plant in that technology group

- `growth_bin_size_mult.csv`: Multiplier [unitless] setting the size of each growth bin relative to the prior solve year's annual deployment

- `growth_limit_absolute.csv`: Maximum allowed annual builds [MW/year] for specified technology groups, based on anticipated record builds from 2024-2026
  - Applied only when `GSw_GrowthAbsCon` is on (off by default), from the first year of new builds through `GSw_GrowthConLastYear`

- `growth_penalty.csv`: Multiplier penalty [unitless] applied to the capital cost for growth in each bin
