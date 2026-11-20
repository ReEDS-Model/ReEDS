## Temporal Input Files

- `month2quarter.csv`: Map from calendar month to quarter (winter, spring, summer, fall)

- `period_szn_user.csv`: User-specified assignment of each actual period to the representative period that stands in for it
  - Used when the `GSw_HourlyClusterAlgorithm` switch contains the substring `user`, which bypasses the clustering algorithms

- `stressperiods_user.csv`: User-specified stress periods by model year
  - Used when the `GSw_PRM_StressModel` switch starts with `user`, which bypasses stress period identification by PRAS
