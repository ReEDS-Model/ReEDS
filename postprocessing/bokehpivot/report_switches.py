'''User switches for the value/cost-factor report and the figures built from it.

run_report_valcostfac.py builds the report, then plcoe_pitch.py and reeds_vs_rev.py render figures
from its output. The switches live here rather than in run_report_valcostfac.py so all three read the
same values: run_report_valcostfac.py cannot be imported to share them, because importing it rebuilds
the whole report and it imports plcoe_pitch.py in turn.

dollar_year is the one that most needs sharing - the figures label their axes with it while the
report converts the data into it, so a disagreement would silently mislabel every $ chart.

This file is copied into the report's output_dir alongside run_report_valcostfac.py, so the settings
behind a given report stay recorded with it.

Switches that only affect one figure stay with that figure (plcoe_pitch.py and reeds_vs_rev.py each
keep their own user inputs at the top).
'''

dollar_year = 2024 #Dollar year for every $ output and axis label. Report values, LCOE_base and the PTC arrive on three different bases and are all converted into it, so they can be mixed.
lcoe_base_dollar_year = 2022 #Dollar year of LCOE_base.csv as written (2024 ATB). Only change this if that file is regenerated on a different basis.
start_year = 2025 #First year of results to include (first endogenous year, without prescribed builds)
share_basis = 'gen' #Denominator for gen_frac (used by all plots and adjusted metrics): 'load' = busbar load; 'gen' = total generation excluding storage. Both columns (gen_frac_load, gen_frac_gen) are retained in valcostfac.csv regardless.
gen_frac_max = 0.65 #Upper limit on gen_frac for the intermediary "lim" plots
vcf_min = 0 #Minimum value_cost_factor_adj2 to retain in df_plot_core
stor_report_techs = ['Battery'] #Techs whose gen_twh/generation is overridden with gross discharge
storage_techs = ['Pumped-Hydro','Pumped-Hydro-Flex','Battery','EVMC_Storage','CAES'] #Techs excluded from the total-generation market-share denominator
metrics_subreg = ['vf','vcf'] #Metrics to plot vs gen_frac for each subregion (transreg/interconnect)
