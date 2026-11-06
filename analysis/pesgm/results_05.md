## 5. Dial sensitivity from the full factorial (exact ANOVA shares)

cost_total: main effects explain 79 % of its variance across the 486 runs (largest Fuel 60 %, then Pol 10 %, REcost 8 %), two-way interactions 10 % and higher-order terms 11 %; the RF OOF predictions attribute 67 % to Fuel and 10 % to two-way terms, and RF permutation importance ranks Fuel (62 %) then REcost (16 %).
tran_total: main effects explain 86 % of its variance across the 486 runs (largest Fuel 71 %, then REcost 4 %, Siting 4 %), two-way interactions 11 % and higher-order terms 3 %; the RF OOF predictions attribute 74 % to Fuel and 10 % to two-way terms, and RF permutation importance ranks Fuel (71 %) then Siting (10 %).
cap_wind-ons: main effects explain 94 % of its variance across the 486 runs (largest Fuel 73 %, then REcost 14 %, Dem 5 %), two-way interactions 4 % and higher-order terms 1 %; the RF OOF predictions attribute 74 % to Fuel and 4 % to two-way terms, and RF permutation importance ranks Fuel (73 %) then REcost (14 %).
gen_wind-ons: main effects explain 95 % of its variance across the 486 runs (largest Fuel 66 %, then REcost 19 %, Dem 6 %), two-way interactions 4 % and higher-order terms 1 %; the RF OOF predictions attribute 67 % to Fuel and 4 % to two-way terms, and RF permutation importance ranks Fuel (66 %) then REcost (19 %).
cap_upv: main effects explain 85 % of its variance across the 486 runs (largest Fuel 49 %, then Dem 18 %, Pol 7 %), two-way interactions 12 % and higher-order terms 3 %; the RF OOF predictions attribute 52 % to Fuel and 12 % to two-way terms, and RF permutation importance ranks Fuel (54 %) then Dem (18 %).
gen_upv: main effects explain 85 % of its variance across the 486 runs (largest Fuel 41 %, then Dem 21 %, REcost 8 %), two-way interactions 12 % and higher-order terms 3 %; the RF OOF predictions attribute 44 % to Fuel and 13 % to two-way terms, and RF permutation importance ranks Fuel (46 %) then Dem (21 %).
cap_gas-cc: main effects explain 86 % of its variance across the 486 runs (largest Fuel 48 %, then REcost 23 %, Pol 8 %), two-way interactions 10 % and higher-order terms 4 %; the RF OOF predictions attribute 51 % to Fuel and 9 % to two-way terms, and RF permutation importance ranks Fuel (52 %) then REcost (25 %).
gen_gas-cc: main effects explain 93 % of its variance across the 486 runs (largest Fuel 72 %, then REcost 14 %, Dem 4 %), two-way interactions 5 % and higher-order terms 2 %; the RF OOF predictions attribute 73 % to Fuel and 5 % to two-way terms, and RF permutation importance ranks Fuel (72 %) then REcost (17 %).
cap_battery_li: main effects explain 77 % of its variance across the 486 runs (largest Batt 59 %, then Fuel 16 %, Pol 1 %), two-way interactions 13 % and higher-order terms 9 %; the RF OOF predictions attribute 64 % to Batt and 13 % to two-way terms, and RF permutation importance ranks Batt (61 %) then Fuel (24 %).
gen_battery_li: main effects explain 80 % of its variance across the 486 runs (largest Batt 57 %, then Fuel 19 %, Siting 2 %), two-way interactions 11 % and higher-order terms 8 %; the RF OOF predictions attribute 62 % to Batt and 10 % to two-way terms, and RF permutation importance ranks Batt (58 %) then Fuel (25 %).
cap_gas-ct: main effects explain 72 % of its variance across the 486 runs (largest REcost 20 %, then Fuel 17 %, Pol 16 %), two-way interactions 20 % and higher-order terms 8 %; the RF OOF predictions attribute 22 % to REcost and 19 % to two-way terms, and RF permutation importance ranks Fuel (29 %) then REcost (24 %).
gen_gas-ct: main effects explain 58 % of its variance across the 486 runs (largest Fuel 29 %, then Dem 13 %, Batt 8 %), two-way interactions 30 % and higher-order terms 13 %; the RF OOF predictions attribute 37 % to Fuel and 29 % to two-way terms, and RF permutation importance ranks Fuel (44 %) then Dem (26 %).
cap_nuclear: main effects explain 2 % of its variance across the 486 runs (largest Dem 0 %, then Fuel 0 %, REcost 0 %), two-way interactions 10 % and higher-order terms 87 %; the RF OOF predictions attribute 0 % to Dem and 33 % to two-way terms, and RF permutation importance ranks Fuel (29 %) then REcost (22 %).
gen_nuclear: main effects explain 68 % of its variance across the 486 runs (largest Fuel 36 %, then REcost 22 %, Batt 7 %), two-way interactions 15 % and higher-order terms 17 %; the RF OOF predictions attribute 43 % to Fuel and 16 % to two-way terms, and RF permutation importance ranks Fuel (42 %) then REcost (24 %).

Across the 14 headline outputs and 6 dials, the RF share of each main effect differs from the ReEDS share by 1.3 points on average (max 7.4 points, for Fuel on gen_nuclear); on average the RF predictions put +4.7 points more of their variance into main effects, +1.5 points into two-way interactions and -6.1 points into higher-order terms than the ReEDS outputs do, i.e. the out-of-fold surrogate reproduces the main-effect and pairwise structure and smooths away part of the three-way-and-higher variance.
The dominant dial is the same in ReEDS and in the RF predictions for 93 % of headline outputs, and permutation importance picks the same dominant dial for 86 %.
Averaged over the headline outputs the dials rank Fuel (43 %), Batt (11 %), REcost (10 %), Dem (6 %), Pol (4 %), Siting (2 %), with two-way interactions at 12 % and higher-order terms at 12 %.

Variance shares (ReEDS outputs):

| output | Batt | Dem | Fuel | Pol | REcost | Siting | two-way | higher |
|---|---|---|---|---|---|---|---|---|
| cost_total | 0.1 | 1.1 | 59.5 | 9.6 | 7.7 | 0.9 | 10.5 | 10.6 |
| tran_total | 0.2 | 3.8 | 70.6 | 2.8 | 4.4 | 4.3 | 11.0 | 3.0 |
| cap_wind-ons | 0.9 | 5.0 | 72.9 | 1.6 | 13.8 | 0.2 | 4.4 | 1.1 |
| gen_wind-ons | 0.4 | 5.9 | 65.6 | 1.9 | 18.7 | 2.8 | 3.7 | 1.0 |
| cap_upv | 4.1 | 17.8 | 49.1 | 7.4 | 5.2 | 1.8 | 11.7 | 2.9 |
| gen_upv | 5.8 | 20.7 | 40.9 | 5.7 | 7.8 | 3.8 | 12.2 | 3.1 |
| cap_gas-cc | 0.2 | 3.9 | 48.3 | 7.6 | 23.1 | 2.8 | 9.7 | 4.3 |
| gen_gas-cc | 0.0 | 4.5 | 71.9 | 2.6 | 14.0 | 0.1 | 5.2 | 1.7 |
| cap_battery_li | 58.6 | 0.3 | 15.9 | 1.1 | 0.6 | 0.8 | 13.2 | 9.4 |
| gen_battery_li | 56.6 | 0.7 | 18.8 | 0.9 | 1.3 | 2.0 | 11.4 | 8.2 |
| cap_gas-ct | 15.1 | 1.7 | 16.6 | 16.2 | 20.0 | 2.1 | 20.4 | 7.9 |
| gen_gas-ct | 8.5 | 12.8 | 29.2 | 1.2 | 0.1 | 5.9 | 29.6 | 12.7 |
| cap_nuclear | 0.4 | 0.4 | 0.4 | 0.2 | 0.4 | 0.4 | 10.3 | 87.4 |
| gen_nuclear | 7.4 | 1.0 | 35.8 | 2.1 | 22.1 | 0.0 | 14.7 | 16.9 |

Variance shares (RF OOF predictions):

| output | Batt | Dem | Fuel | Pol | REcost | Siting | two-way | higher |
|---|---|---|---|---|---|---|---|---|
| cost_total | 0.0 | 0.5 | 66.8 | 10.0 | 7.9 | 1.0 | 9.9 | 3.8 |
| tran_total | 0.1 | 3.4 | 73.8 | 2.4 | 4.2 | 3.9 | 10.3 | 1.8 |
| cap_wind-ons | 0.4 | 4.7 | 74.5 | 1.2 | 13.9 | 0.1 | 4.4 | 0.8 |
| gen_wind-ons | 0.1 | 5.1 | 67.2 | 1.2 | 19.3 | 2.0 | 4.4 | 0.8 |
| cap_upv | 2.9 | 18.7 | 51.6 | 6.8 | 5.5 | 0.8 | 11.7 | 1.8 |
| gen_upv | 4.4 | 22.4 | 43.6 | 4.7 | 7.5 | 2.2 | 13.1 | 2.2 |
| cap_gas-cc | 0.0 | 3.6 | 51.5 | 7.2 | 24.4 | 2.2 | 8.8 | 2.3 |
| gen_gas-cc | 0.0 | 4.2 | 72.8 | 2.5 | 14.2 | 0.1 | 5.0 | 1.1 |
| cap_battery_li | 63.7 | 0.3 | 17.0 | 0.7 | 0.4 | 0.7 | 12.9 | 4.3 |
| gen_battery_li | 62.2 | 0.4 | 20.1 | 0.6 | 0.9 | 1.7 | 9.9 | 4.1 |
| cap_gas-ct | 15.7 | 1.6 | 18.6 | 18.2 | 21.8 | 1.2 | 19.3 | 3.6 |
| gen_gas-ct | 7.9 | 15.1 | 36.6 | 1.2 | 0.2 | 5.1 | 29.3 | 4.7 |
| cap_nuclear | 0.4 | 0.5 | 7.1 | 2.9 | 7.1 | 0.7 | 33.3 | 48.1 |
| gen_nuclear | 7.7 | 0.4 | 43.3 | 1.7 | 26.0 | 0.0 | 15.9 | 5.1 |

RF permutation importance (normalised share, %):

| output | Batt | Dem | Fuel | Pol | REcost | Siting |
|---|---|---|---|---|---|---|
| cost_total | 1.3 | 4.8 | 61.7 | 10.9 | 16.4 | 5.0 |
| tran_total | 0.5 | 8.2 | 71.0 | 4.6 | 5.9 | 9.8 |
| cap_wind-ons | 1.4 | 7.0 | 73.1 | 2.4 | 14.4 | 1.7 |
| gen_wind-ons | 0.6 | 7.9 | 66.2 | 2.6 | 19.2 | 3.4 |
| cap_upv | 5.6 | 18.3 | 53.5 | 9.9 | 9.8 | 2.9 |
| gen_upv | 7.6 | 21.0 | 46.4 | 8.0 | 11.7 | 5.2 |
| cap_gas-cc | 0.7 | 7.2 | 51.8 | 10.3 | 25.0 | 5.0 |
| gen_gas-cc | 0.2 | 5.6 | 72.4 | 4.4 | 16.5 | 0.8 |
| cap_battery_li | 61.1 | 3.4 | 23.8 | 3.5 | 3.3 | 4.9 |
| gen_battery_li | 57.9 | 3.7 | 25.1 | 3.8 | 3.7 | 5.8 |
| cap_gas-ct | 15.6 | 6.8 | 28.9 | 21.0 | 23.8 | 4.0 |
| gen_gas-ct | 10.3 | 25.7 | 43.5 | 3.7 | 4.8 | 11.9 |
| cap_nuclear | 11.6 | 13.4 | 28.6 | 12.9 | 21.6 | 11.9 |
| gen_nuclear | 11.7 | 6.0 | 42.0 | 5.0 | 24.2 | 11.1 |

Figures: figs/fig05a_variance_shares (stacked shares, ReEDS outputs), figs/fig05b_truth_vs_rf (ReEDS vs RF share per output-dial pair).
