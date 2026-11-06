# Known limits of the constraint layer (not fixed)

These remaining inconsistencies were found after the final constraint-layer change on 2026-11-06.
By decision, the code is frozen for the paper deadline. They are recorded here and not fixed.
Counts are RF out-of-fold predictions over the 486 runs after all rules, unless a row says otherwise.
The source is `10_after_fix.py` (`data/10_*`).

| # | Limit | Count | Description |
|---|---|---|---|
| 1 | Capacity-factor ceiling | 993 of 29,519 regional predictions (796 of 29,658 raw); 170 of 7,183 system | Predicted gen / (8760 × cap) is more than 1% above the observed maximum CF for that technology and region. No rule ties generation to capacity. |
| 2 | Additivity skipped for signed quantities | 1,031 of the 1,167 remaining regional-sum violations (gen_battery_li 451, gen_pumped-hydro 356, cost_op_ptc_payments_negative 224) | The mixed-sign guard does not rescale quantities with negative regional values, so their regional sum can differ from the system value by more than 1%. |
| 3 | Nothing to scale for rare technologies | 136 of the 1,167 remaining violations (mostly H2 and CCS technologies) | The regional prediction sums to 0 while the system prediction is positive, so the rescale has nothing to scale. |
| 4 | System predicts 0, regions do not | 1,458 run-quantity pairs (left out of the 1% metric's denominator) | When the system value is 0, the rescale is skipped, so small regional values remain for a technology the system says is not built. |
| 5 | `tran_AC_total` not floored | MLP 37, Ridge 90 system runs more than 1% below the total initial capacity (RF 0) | Only `tran_total` is clipped to 34,478.6 MW. The duplicate AC total is left as predicted. |
| 6 | Regional "System cost" line differs from the system line | for example $22.26 B vs $22.14 B (RF, Md/IRA training design) | On the regional layer the dashboard's total is the sum of regional cost components, and skipped quantities (row 2) keep their regional values. |
| 7 | Rare-H2 amplification for MLP | MLP regional mean R² 0.547 raw vs 0.006 constrained (worst output: cost_inv_h2_production_p62, R² −145.6) | A spurious system H2 total is rescaled into the one region with a small positive value. This does not affect Table III (raw scores) or RF. |
| 8 | XGBoost artifacts not loadable outside training | 2 artifacts (overall, regional) | They were pickled with `MonotoneXGBMultiOutput` under `__main__`, so the dashboard cannot load XGBoost without an alias. This predates the fix. |
| 9 | August deliverables describe the dGen curve | 2 lines (OneDrive `Final_Report.md:73`, `slides.html:146`) | The DistPV curve is removed in code (held constant), and those delivered documents were not edited. |
| 11 | XGBoost monotone hints contradict the data for the fuel and siting dials | Fuel: 2 rules (`surrogate_constraints.py:163, 179`). Siting: the −1 hint on UPV and wind capacity and on UPV generation (`:168-169, 182-183`) | **Fuel:** the hints assume a higher x_Fuel means a higher gas price, but x_Fuel = 0 is `AEO_2025_LOG`, the high-price case (gas-CC generation is 62 / 249 / 329 TWh at x_Fuel = 0 / 1 / 2). **Siting:** tighter siting raises mean UPV capacity (88 → 97 GW) and generation (192 → 222 TWh) and wind capacity (87 → 90 GW); only wind generation falls. Both were found during the claims check and affect only the XGBoost fit. |
| 10 | Pre-fix check script no longer runs | 1 script (`09_constraints_check.py`) | It imports the removed DistPV function. It is kept as the record of the pre-fix state. |
