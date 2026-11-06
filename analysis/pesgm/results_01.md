## 1. Interval calibration (10-fold OOF, seed 42)

The RF out-of-fold predictions used here reproduce the stored residuals exactly (max relative difference 9.4e-07 of the output std). NGBoost had to be re-run to obtain the predicted sigma; its default tree learner is unseeded (random_state=None), so individual predictions differ from the stored run (max relative difference 0.44 std) while the aggregate accuracy is unchanged: re-run mean / median R-squared 0.7109 / 0.8149 (system) and 0.5589 / 0.5898 (regional) versus stored 0.7107 / 0.8147 and 0.5588 / 0.5898.
**system layer (66 outputs)**

The deployed RF split-conformal 90 % band, calibrated on the other nine folds and evaluated on the held-out fold, covers the true value in 90.2 % of held-out runs on average across outputs (median 89.9 %, range 89.3-100.0 %); 97 % of outputs are within 5 points of nominal.
At 50/80/95 % nominal the RF conformal band covers 56.3/80.9/95.0 %.
The in-sample number the existing eval code reports for the same band is 90.3 % at 90 % nominal; it is circular (width and coverage from the same residuals) and should not be cited.
The RF-native per-tree 5-95 % quantile band is badly under-covered: 85.9 % mean coverage at 90 % nominal (64.5/80.2/89.3 % at 50/80/95 %), which is why the conformal wrapper is needed.
The NGBoost native Normal 90 % interval covers 88.2 % on average (median 88.6 %, 5 % of outputs under-covered by more than 10 points); at 50/80/95 % it covers 48.4/78.1/93.3 %.
A split-conformal correction of the NGBoost sigma (cross-fold quantile of |residual|/sigma replacing z) restores 89.8 % coverage at 90 % nominal (50.1/79.8/94.8 % at 50/80/95 %).
Sharpness at 90 %: median half-width / std(y) is 0.29 for RF conformal, 0.24 for the RF per-tree band and 0.41 for NGBoost native.
Most under-covered outputs for the RF conformal 90 % band: cost_inv_itc_payments_negative (89 %), gen_wind-ons (90 %), gen_H2-CT (90 %), gen_battery_li (90 %), gen_CoalOldScr (90 %). Most over-covered: gen_distpv (100 %), gen_hydEND (100 %), cap_nuclear (93 %), cap_gas-cc-ccs_mod (90 %), cost_inv_transmission_intrazone_investment (90 %).
Most under-covered outputs for the NGBoost native 90 % band: gen_wind-ons (78 %), cost_op_fom_costs (80 %), cost_op_vom_costs (80 %), gen_upv (80 %), cap_wind-ons (81 %).

**regional layer (308 outputs)**

The deployed RF split-conformal 90 % band, calibrated on the other nine folds and evaluated on the held-out fold, covers the true value in 90.2 % of held-out runs on average across outputs (median 89.9 %, range 89.1-100.0 %); 97 % of outputs are within 5 points of nominal.
At 50/80/95 % nominal the RF conformal band covers 57.2/80.9/95.0 %.
The in-sample number the existing eval code reports for the same band is 90.3 % at 90 % nominal; it is circular (width and coverage from the same residuals) and should not be cited.
The RF-native per-tree 5-95 % quantile band is badly under-covered: 87.9 % mean coverage at 90 % nominal (68.2/82.6/91.1 % at 50/80/95 %), which is why the conformal wrapper is needed.
The NGBoost native Normal 90 % interval covers 89.4 % on average (median 90.3 %, 1 % of outputs under-covered by more than 10 points); at 50/80/95 % it covers 49.8/79.9/94.1 %.
A split-conformal correction of the NGBoost sigma (cross-fold quantile of |residual|/sigma replacing z) restores 89.8 % coverage at 90 % nominal (50.2/79.9/94.7 % at 50/80/95 %).
Sharpness at 90 %: median half-width / std(y) is 0.44 for RF conformal, 0.30 for the RF per-tree band and 0.49 for NGBoost native.
Most under-covered outputs for the RF conformal 90 % band: cost_op_h2_transport_intrareg_p63 (89 %), cap_gas-cc_p63 (89 %), cap_H2-CT_p61 (89 %), cost_op_fom_costs_p60 (89 %), cap_H2-CT_p63 (89 %). Most over-covered: gen_hydEND_p63 (100 %), gen_hydEND_p65 (100 %), gen_distpv_p62 (100 %), gen_distpv_p63 (100 %), gen_distpv_p64 (100 %).
Most under-covered outputs for the NGBoost native 90 % band: cap_upv_p65 (78 %), cap_gas-cc_p63 (78 %), cost_op_fuelcosts_objfn_p67 (80 %), gen_upv_p65 (80 %), cap_gas-ct_p60 (80 %).

Summary table (mean coverage over outputs):

| layer | method | 0.5 | 0.8 | 0.9 | 0.95 |
|---|---|---|---|---|---|
| regional | ngb_conformal | 0.502 | 0.799 | 0.898 | 0.947 |
| regional | ngb_native | 0.498 | 0.799 | 0.894 | 0.941 |
| regional | rf_conformal | 0.572 | 0.809 | 0.902 | 0.950 |
| regional | rf_conformal_insample | 0.572 | 0.811 | 0.903 | 0.950 |
| regional | rf_tree_quantile | 0.682 | 0.826 | 0.879 | 0.911 |
| system | ngb_conformal | 0.501 | 0.798 | 0.898 | 0.948 |
| system | ngb_native | 0.484 | 0.781 | 0.882 | 0.933 |
| system | rf_conformal | 0.563 | 0.809 | 0.902 | 0.950 |
| system | rf_conformal_insample | 0.563 | 0.811 | 0.903 | 0.950 |
| system | rf_tree_quantile | 0.645 | 0.802 | 0.859 | 0.893 |

Figures: figs/fig01a_reliability (nominal vs empirical, solid = system, dotted = regional), figs/fig01b_coverage_hist (per-output 90 % coverage).
