# GAMS reference equations

The ReEDS GAMS source for every equation in the slice, copied verbatim (comments included) so the code can be checked without a ReEDS checkout.

- Source: https://github.com/ReEDS-Model/ReEDS, commit `ea3bcbf` (5 Oct 2026). The older NREL/ReEDS-2.0 repository is archived.
- `eq_*.gms` other than the objective: `reeds/core/setup/c_model.gms`. Line numbers: eq_loadcon 350, eq_cap_init_noret 585, eq_cap_new_noret 693, eq_cap_energy_new_noret 730, eq_rsc_inv_account 1008, eq_rsc_INVlim 1024, eq_capacity_limit 1187, eq_capacity_limit_nd 1257, eq_supply_demand_balance 1400, eq_CAPTRAN_ENERGY 1907, eq_CAPTRAN_PRM 1932, eq_transmission_limit 2015, eq_emit_accounting 2370, eq_annual_cap 2493, eq_storage_capacity 3001, eq_storage_level 3044, eq_storage_duration 3143.
- `eq_ObjFn*.gms`, `eq_Objfn_op.gms`: `reeds/core/setup/d_objective.gms`.

These are the full equations with every switch. The slice uses the subset active under the switch profile in `../../FORMULATION.md`; `../per_constraint_comparison.md` shows each trimmed GAMS equation next to its pyoframe and Pyomo code.
