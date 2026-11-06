## 6. Failure classes: sparse and near-constant outputs

**system layer (66 outputs)**: 23 outputs are sparse (non-zero in fewer than 50 % of runs) with mean / median R-squared 0.56 / 0.55; 2 are near-constant (CV < 2 %) with mean / median R-squared 0.32 / 0.32; the remaining 41 regular outputs have mean / median R-squared 0.877 / 0.925.
Of the 12 system outputs with R-squared below 0.5, 11 are sparse and 1 are near-constant, so 100 % of the low-R-squared outputs fall in the two failure classes.
Spearman correlation of per-output R-squared with activation frequency is 0.61 and with coefficient of variation -0.62 (system).
**regional layer (308 outputs)**: 129 outputs are sparse (non-zero in fewer than 50 % of runs) with mean / median R-squared 0.42 / 0.52; 5 are near-constant (CV < 2 %) with mean / median R-squared 0.73 / 1.00; the remaining 174 regular outputs have mean / median R-squared 0.775 / 0.832.
Of the 85 regional outputs with R-squared below 0.5, 62 are sparse and 1 are near-constant, so 74 % of the low-R-squared outputs fall in the two failure classes.
Spearman correlation of per-output R-squared with activation frequency is 0.69 and with coefficient of variation -0.63 (regional).

cap_nuclear takes only 2 distinct values across the 486 runs (CV 0.07 %); its OOF R-squared is -0.36 but its MAE is 0.012 % of the mean, so the low R-squared is a metric artefact of a near-constant denominator, not a prediction failure.
Headline-output absolute errors (RF, 10-fold OOF): cost_total R-squared 0.90, MAE 7.4 % of mean; tran_total R-squared 0.97, MAE 2.8 % of mean; cap_wind-ons R-squared 0.99, MAE 2.8 % of mean; gen_wind-ons R-squared 0.99, MAE 3.0 % of mean; cap_upv R-squared 0.97, MAE 4.0 % of mean; gen_upv R-squared 0.96, MAE 4.5 % of mean; cap_gas-cc R-squared 0.95, MAE 4.6 % of mean; gen_gas-cc R-squared 0.99, MAE 4.5 % of mean; cap_battery_li R-squared 0.93, MAE 12.8 % of mean; gen_battery_li R-squared 0.94, MAE 13.9 % of mean; cap_gas-ct R-squared 0.89, MAE 8.0 % of mean; gen_gas-ct R-squared 0.87, MAE 12.1 % of mean; cap_nuclear R-squared -0.36, MAE 0.0 % of mean; gen_nuclear R-squared 0.84, MAE 0.6 % of mean.

Headline table:

| output | r2 | activation | cv | mae_pct_of_mean | rmse_pct_of_range | class |
|---|---|---|---|---|---|---|
| cost_total | 0.898 | 1.000 | 0.326 | 7.408 | 6.215 | regular |
| tran_total | 0.975 | 1.000 | 0.267 | 2.797 | 3.480 | regular |
| cap_wind-ons | 0.989 | 1.000 | 0.350 | 2.832 | 2.438 | regular |
| gen_wind-ons | 0.986 | 1.000 | 0.332 | 3.019 | 2.406 | regular |
| cap_upv | 0.967 | 1.000 | 0.288 | 3.962 | 4.012 | regular |
| gen_upv | 0.963 | 1.000 | 0.303 | 4.486 | 4.264 | regular |
| cap_gas-cc | 0.953 | 1.000 | 0.272 | 4.580 | 5.444 | regular |
| gen_gas-cc | 0.990 | 1.000 | 0.618 | 4.491 | 3.074 | regular |
| cap_battery_li | 0.926 | 1.000 | 0.659 | 12.777 | 6.857 | regular |
| gen_battery_li | 0.941 | 1.000 | 0.807 | 13.866 | 6.413 | regular |
| cap_gas-ct | 0.893 | 1.000 | 0.308 | 7.969 | 6.541 | regular |
| gen_gas-ct | 0.869 | 1.000 | 0.568 | 12.053 | 5.097 | regular |
| cap_nuclear | -0.362 | 1.000 | 0.001 | 0.012 | 5.288 | near-constant |
| gen_nuclear | 0.842 | 1.000 | 0.023 | 0.648 | 6.709 | regular |

Figure: figs/fig06_r2_vs_activation_cv (left: R-squared vs activation frequency; right: vs CV, log scale; large markers = system layer, faint = regional; near-constant and low-R-squared sparse system outputs labelled).
