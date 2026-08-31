## National Generation Input Files

### Input files

- `gen_mandate_trajectory.csv`: Required clean generation share [fraction] by year for each national generation standard trajectory
  - Rows are the trajectory names; the row used is selected by the `GSw_GenMandateScen` switch

- `nat_gen_tech_frac.csv`: Fraction [fraction] of each technology's generation that counts toward the national generation standard, given separately for the `RE`, `Nuclear`, `NuclearCCS`, and `RE_NoCombust` technology lists
  - The column used is selected by the `GSw_GenMandateList` switch

- `national_rps_frac_allScen.csv`: Required national RPS share [fraction] by year for a range of named scenarios
  - Used when `GSw_StateRPS` is on