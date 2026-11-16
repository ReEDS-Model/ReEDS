## Valuestreams Input Files

- `var_map.csv`: Map from ReEDS optimization variable names to the position of each index (`i`, `v`, `r`, `h`, `t`) within that variable
  - Used by `postprocessing/valuestreams.py` to parse variables out of the solution file; a blank entry means the variable does not carry that index
