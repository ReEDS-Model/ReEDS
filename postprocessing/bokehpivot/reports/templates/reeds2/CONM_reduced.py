#Same sections as standard_report_reduced, using BA-level results summed over Colorado and New Mexico.
#System cost and runtime are national only, so they're not included.
conm = {'filter': {'st': ['co','nm']}}
static_presets = [
    {'name': 'CO+NM Generation (TWh)', 'sheet_name':'gen', 'result': 'Generation BA (TWh)', 'preset': 'Stacked Bars', 'config': conm},
    {'name': 'CO+NM Capacity (GW)', 'sheet_name':'cap', 'result': 'Capacity BA (GW)', 'preset': 'Stacked Bars', 'config': conm},
    {'name': 'CO+NM New Annual Capacity (GW)', 'sheet_name':'cap_new_ann', 'result': 'New Annual Capacity BA (GW)', 'preset': 'Stacked Bars', 'config': conm},
    {'name': 'CO+NM Annual Retirements (GW)', 'sheet_name':'retire_ann', 'result': 'Annual Retirements BA (GW)', 'preset': 'Stacked Bars', 'config': conm},
    {'name': 'CO+NM Final Gen by timeslice (GW)', 'sheet_name':'gen_final_timeslice', 'result': 'Gen by timeslice regional (GW)', 'preset': 'Stacked Bars Final', 'config': conm},
    {'name': 'CO+NM Bulk System Electricity Price ($/MWh)', 'sheet_name':'elec_price', 'result': 'Requirement Prices and Quantities BA Annual', 'preset': 'Bulk System Electricity Price ($/MWh)', 'config': conm},
    {'name': 'CO+NM CO2 Emissions (metric tons)', 'sheet_name':'emissions', 'result': 'CO2 Emissions BA (metric tons)', 'preset': 'Scenario Lines Over Time', 'config': conm},
]
