## 7. Regional layer detail (RF, 10-fold OOF)

The regional layer has 308 modelled outputs across 298 BA-resolved columns in 7 balancing areas plus 10 transmission corridors (an 11th corridor is constant and dropped); per region: corridor 10 outputs, mean / median R-squared 0.79 / 0.86, 3 at >= 0.9; p60 35 outputs, mean / median R-squared 0.54 / 0.61, 2 at >= 0.9; p61 36 outputs, mean / median R-squared 0.74 / 0.84, 8 at >= 0.9; p62 37 outputs, mean / median R-squared 0.57 / 0.66, 4 at >= 0.9; p63 50 outputs, mean / median R-squared 0.64 / 0.81, 16 at >= 0.9; p64 45 outputs, mean / median R-squared 0.64 / 0.60, 13 at >= 0.9; p65 49 outputs, mean / median R-squared 0.62 / 0.75, 14 at >= 0.9; p67 46 outputs, mean / median R-squared 0.59 / 0.79, 16 at >= 0.9.
The best-predicted region is corridor (mean R-squared 0.79) and the worst is p60 (0.54); mean activation frequency of the outputs is 1.00 versus 0.58, so regional difficulty tracks how many sparse tech-region combinations a BA has.
By category within region, cap outputs have mean R-squared from 0.52 (p65) to 0.70 (p61).
By category within region, gen outputs have mean R-squared from 0.55 (p62) to 0.77 (p61).
By category within region, cost outputs have mean R-squared from 0.49 (p60) to 0.74 (p61).

Additivity before rescaling: across the 63 quantities present in both layers, the sum of the raw regional RF predictions differs from the system RF prediction by a median of 2.21 % of the system value (median over quantities of the per-quantity median absolute gap), exceeds 1 % in 59 % of (run, quantity) pairs and 5 % in 31 %.
For the headline quantities the median absolute gap is cap_wind-ons 2.14 % (p90 5.9 %), cap_upv 2.74 % (p90 6.7 %), cap_gas-cc 1.60 % (p90 4.1 %), cap_battery_li 5.23 % (p90 14.4 %), cap_gas-ct 3.49 % (p90 8.6 %), gen_wind-ons 2.12 % (p90 5.4 %), gen_upv 2.71 % (p90 7.2 %), gen_gas-cc 2.07 % (p90 7.0 %), tran_total 0.99 % (p90 4.2 %).
The sum of regional predictions is itself a competitive estimate of the system total: R-squared against the ReEDS system value is cap_wind-ons 0.988 (system model 0.989), cap_upv 0.972 (system model 0.967), cap_gas-cc 0.961 (system model 0.953), cap_battery_li 0.932 (system model 0.926), cap_gas-ct 0.918 (system model 0.893), gen_wind-ons 0.987 (system model 0.986), gen_upv 0.969 (system model 0.963), gen_gas-cc 0.991 (system model 0.990), tran_total 0.982 (system model 0.975).
Quantities whose regional sum misses the system prediction by more than 5 % in over a quarter of runs: cost_inv_investment_capacity_costs, cost_inv_investment_spurline_costs_rsc_technologies, cost_inv_transmission_interzone_ac_investment, cost_inv_transmission_intrazone_investment, cost_op_ptc_payments_negative, cost_op_startcost, cost_inv_investment_refurbishment_capacity, gen_upv, cost_op_co2_transport_storage, gen_gas-ct, cost_op_h2_transport_intrareg, cost_op_consume_fom, gen_battery_li, cost_op_h2_storage, cost_inv_h2_production, gen_CoalOldScr, gen_CoalOldScr_coal-CCS_mod, cost_inv_h2_storage, gen_o-g-s, gen_H2-CT, gen_H2-CC, cap_gas-ct, gen_Gas-CC_H2-CC, cap_battery_li, cap_gas-cc-ccs_mod, cap_CoalOldScr_coal-CCS_mod, cap_CoalOldScr, cap_H2-CT, cap_electrolyzer, cap_H2-CC, cap_Gas-CC_H2-CC.
Because the dashboard does not call enforce_additivity, these pre-rescale gaps are what a user sees when comparing the regional and system views.

Per-region table:

| region | n_outputs | r2_mean | r2_median | n_ge_0_9 | n_below_0_5 | mean_activation |
|---|---|---|---|---|---|---|
| corridor | 10 | 0.786 | 0.856 | 3 | 2 | 1.000 |
| p60 | 35 | 0.540 | 0.607 | 2 | 13 | 0.581 |
| p61 | 36 | 0.738 | 0.839 | 8 | 5 | 0.623 |
| p62 | 37 | 0.568 | 0.656 | 4 | 13 | 0.561 |
| p63 | 50 | 0.639 | 0.814 | 16 | 16 | 0.568 |
| p64 | 45 | 0.641 | 0.595 | 13 | 11 | 0.615 |
| p65 | 49 | 0.616 | 0.750 | 14 | 12 | 0.579 |
| p67 | 46 | 0.592 | 0.793 | 16 | 13 | 0.621 |

Additivity residual table (sorted by magnitude of the quantity):

| quantity | n_regions | median_abs_gap_vs_system_pred_pct | p90_abs_gap_vs_system_pred_pct | frac_gap_gt_1pct | frac_gap_gt_5pct | mean_signed_gap_pct | r2_sum_of_regional | r2_system_model |
|---|---|---|---|---|---|---|---|---|
| cost_inv_investment_capacity_costs | 7 | 5.281 | 15.942 | 0.884 | 0.520 | 2.239 | 0.918 | 0.911 |
| cost_op_fom_costs | 7 | 1.018 | 2.676 | 0.502 | 0.002 | 0.057 | 0.975 | 0.980 |
| cost_op_fuelcosts_objfn | 7 | 1.703 | 4.559 | 0.698 | 0.066 | -0.019 | 0.977 | 0.971 |
| cost_inv_investment_spurline_costs_rsc_technologies | 7 | 7.063 | 25.813 | 0.929 | 0.680 | 3953619.755 | 0.901 | 0.893 |
| cost_inv_transmission_interzone_ac_investment | 7 | 7.541 | 29.598 | 0.899 | 0.619 | 878541.838 | 0.882 | 0.873 |
| cost_op_vom_costs | 7 | 1.848 | 5.058 | 0.706 | 0.103 | 0.049 | 0.982 | 0.979 |
| cost_inv_transmission_intrazone_investment | 7 | 9.238 | 30.558 | 0.944 | 0.728 | 11.926 | 0.857 | 0.832 |
| cost_op_transmission_fom | 7 | 0.667 | 3.052 | 0.391 | 0.012 | 0.093 | 0.981 | 0.976 |
| cost_op_spurline_fom | 7 | 1.585 | 4.177 | 0.667 | 0.058 | 0.233 | 0.991 | 0.993 |
| gen_wind-ons | 7 | 2.117 | 5.367 | 0.747 | 0.123 | 0.483 | 0.987 | 0.986 |
| cost_op_ptc_payments_negative | 7 | 6.394 | 24.217 | 0.918 | 0.580 | -5.396 | 0.963 | 0.966 |
| cost_op_startcost | 7 | 5.937 | 13.856 | 0.889 | 0.566 | 1.066 | 0.889 | 0.878 |
| cost_op_transmission_intrazone_fom | 7 | 1.389 | 3.736 | 0.650 | 0.033 | 0.174 | 0.985 | 0.987 |
| cost_inv_investment_refurbishment_capacity | 5 | 13.736 | 51.266 | 0.973 | 0.792 | 9.277 | 0.608 | 0.541 |
| gen_gas-cc | 7 | 2.075 | 6.993 | 0.770 | 0.183 | 0.702 | 0.991 | 0.990 |
| gen_upv | 7 | 2.710 | 7.164 | 0.792 | 0.255 | 0.389 | 0.969 | 0.963 |
| cost_op_co2_transport_storage | 4 | 2.758 | 12.833 | 0.761 | 0.284 | 0.978 | 0.920 | 0.921 |
| gen_nuclear | 2 | 0.064 | 0.207 | 0.000 | 0.000 | -0.006 | 0.841 | 0.842 |
| gen_gas-ct | 7 | 3.522 | 9.933 | 0.848 | 0.348 | 0.701 | 0.872 | 0.869 |
| gen_distpv | 7 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 |
| cost_op_co2_incentive_negative | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.259 | 0.259 |
| gen_gas-cc-ccs_mod | 4 | 2.487 | 8.319 | 0.789 | 0.246 | 0.793 | 0.812 | 0.824 |
| cost_op_h2_transport_intrareg | 7 | 8.941 | 55.774 | 0.952 | 0.667 | 1482005610436140204032.000 | 0.919 | 0.924 |
| cost_op_consume_fom | 7 | 11.416 | 50.913 | 0.976 | 0.707 | 41.138 | 0.907 | 0.918 |
| gen_coal-ccs_mod | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.957 | 0.957 |
| gen_battery_li | 7 | 6.704 | 21.088 | 0.928 | 0.603 | -3.394 | 0.941 | 0.941 |
| cost_op_h2_storage | 7 | 10.655 | 49.900 | 0.945 | 0.659 | 17.779 | 0.938 | 0.944 |
| cost_inv_h2_production | 5 | 35.384 | 86.532 | 1.000 | 0.900 | -8.481 | -0.047 | 0.008 |
| gen_CoalOldScr | 4 | 3.967 | 16.170 | 0.865 | 0.434 | 14659.650 | 0.925 | 0.927 |
| gen_CoalOldScr_coal-CCS_mod | 4 | 5.358 | 17.399 | 0.874 | 0.524 | 4671.579 | 0.735 | 0.720 |
| gen_Gas-CC_Gas-CC-CCS_mod | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.269 | 0.269 |
| cost_inv_h2_storage | 5 | 40.408 | 299.267 | 0.929 | 0.786 | 83.576 | -0.094 | -0.092 |
| gen_o-g-s | 5 | 2.336 | 9.669 | 0.751 | 0.257 | 0.761 | 0.736 | 0.740 |
| gen_hydEND | 4 | 0.000 | 0.000 | 0.000 | 0.000 | -0.000 | 1.000 | 1.000 |
| gen_hydED | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.937 | 0.937 |
| gen_nuclear-smr | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.207 | 0.207 |
| gen_H2-CT | 7 | 12.303 | 51.287 | 0.933 | 0.693 | 3988235.331 | 0.890 | 0.882 |
| gen_H2-CC | 4 | 1.452 | 35.866 | 0.586 | 0.286 | 44.060 | 0.850 | 0.849 |
| gen_lfill-gas | 3 | 0.166 | 0.492 | 0.008 | 0.000 | -0.006 | 0.833 | 0.828 |
| cap_upv | 7 | 2.744 | 6.729 | 0.802 | 0.195 | 0.413 | 0.972 | 0.967 |
| cap_wind-ons | 7 | 2.142 | 5.889 | 0.737 | 0.144 | 0.449 | 0.988 | 0.989 |
| cap_gas-cc | 7 | 1.603 | 4.053 | 0.677 | 0.039 | 0.024 | 0.961 | 0.953 |
| tran_total | 10 | 0.987 | 4.238 | 0.498 | 0.064 | 0.284 | 0.982 | 0.975 |
| cap_gas-ct | 7 | 3.487 | 8.614 | 0.868 | 0.335 | 0.472 | 0.918 | 0.893 |
| gen_Gas-CC_H2-CC | 5 | 18.904 | 48.692 | 1.000 | 0.907 | -3.475 | 0.446 | 0.371 |
| cap_battery_li | 7 | 5.233 | 14.446 | 0.887 | 0.510 | 2.011 | 0.932 | 0.926 |
| gen_pumped-hydro | 2 | 2.205 | 8.711 | 0.733 | 0.212 | 0.041 | 0.566 | 0.568 |
| cap_nuclear | 1 | 0.000 | 0.000 | 0.000 | 0.000 | -0.000 | -0.362 | -0.362 |
| cap_gas-cc-ccs_mod | 4 | 2.761 | 12.072 | 0.708 | 0.327 | 1.728 | 0.871 | 0.872 |
| cap_CoalOldScr_coal-CCS_mod | 4 | 5.364 | 17.134 | 0.890 | 0.519 | 11160.451 | 0.736 | 0.720 |
| cap_coal-ccs_mod | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.925 | 0.925 |
| cap_o-g-s | 5 | 1.571 | 5.546 | 0.658 | 0.121 | 0.254 | 0.593 | 0.599 |
| cap_CoalOldScr | 4 | 4.991 | 16.593 | 0.853 | 0.500 | 5139.890 | 0.803 | 0.804 |
| cap_H2-CT | 7 | 12.141 | 50.590 | 0.933 | 0.693 | 4444657.038 | 0.890 | 0.882 |
| gen_hydUD | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.470 | 0.470 |
| cap_electrolyzer | 7 | 11.635 | 56.764 | 0.963 | 0.707 | 85187065.891 | 0.907 | 0.918 |
| cap_H2-CC | 4 | 1.412 | 36.060 | 0.600 | 0.300 | 26.922 | 0.850 | 0.849 |
| cap_Gas-CC_Gas-CC-CCS_mod | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.299 | 0.299 |
| cap_Gas-CC_H2-CC | 5 | 25.883 | 57.467 | 1.000 | 0.926 | -4.180 | 0.642 | 0.553 |
| cap_nuclear-smr | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.207 | 0.207 |
| cap_pumped-hydro | 1 | 0.000 | 0.324 | 0.080 | 0.033 | 0.021 | 0.562 | 0.561 |
| cost_inv_itc_payments_negative | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.057 | 0.057 |
| cap_hydUD | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.421 | 0.421 |

Figure: figs/fig07_region_r2.
