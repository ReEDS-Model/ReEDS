# BA-level is not used because bokeh has an issue mapping the aggregated BA shapes (e.g. z28)
static_presets = [
    {'name': 'PSH State Capacity Diff - 2025-2050 (GW)', 
     'sheet_name':'diff-cap_psh_2025-2050', 
     'result': 'Capacity ivrt (GW)', 
     'preset': 'State Map Final by Tech',
     'config':{
                'filter':{'year':['2025','2050'],
                        'tech':['Pumped-Hydro']},
                'explode':'scenario','explode_group':'year',
                'adv_op':'Difference', 'adv_col':'year', 'adv_col_base':'2025',
                'plot_title':' ',
                'num_cols':'4',
                'map_bin':'Auto Equal Width', 
                'map_min':'-10', 'map_max':'10', 
                'map_num':'8', 
                'map_palette':'BuRd', 'map_palette_break':'0',
     },
    },
    {'name': 'MAP: New State PSH Capacity - 2025-2050 (GW)',
     'sheet_name':'cap_psh_new_2025-2050',
     'result':'New Capacity BA (GW)',
     'preset':'State Map 2025-2050 Cumulative',
     'config':{'filter':{'tech':['Pumped-Hydro'],},
               'map_bin':'Auto Equal Width', 
               'map_min':'0', 'map_max':'10',
               'map_num':'9', 
               'map_palette':'Blues',
     }  
    },
    {'name':'New State PSH Cumulative Capacity (GW)', 'sheet_name':'cumcap_new_psh_state_bars', 'result':'New Capacity BA (GW)', 'preset':'Stacked Bars Cumulative',
     'config':{
         'series':'st',
         'filter':{'tech':['Pumped-Hydro'],},
         'adv_op':'Difference', 'adv_col':'year', 'adv_col_base':'2025',
         'x_min':'2024', 'x_max':'2051',
         'y_min':'0','y_max':'15',
     }  
    },
    {'name':'New BA PSH Cumulative Capacity (GW)', 'sheet_name':'cumcap_new_psh_state_bars', 'result':'New Capacity BA (GW)', 'preset':'Stacked Bars Cumulative',
     'config':{
         'series':'rb',
         'filter':{'tech':['Pumped-Hydro'],},
         'adv_op':'Difference', 'adv_col':'year', 'adv_col_base':'2025',
         'x_min':'2024', 'x_max':'2051',
         'y_min':'0','y_max':'15',
     }  
    },
    # {'name': 'State Annual PSH Retirements (GW)', 'sheet_name':'ret_ann_psh', 'result': 'Annual Retirements BA (GW)', 'preset': 'Stacked Bars Cumulative',
    #  'config':{
    #      'series':'st',
    #      'filter':{'tech':['Pumped-Hydro'],}}
    # }, 
    # {'name': 'BA Annual PSH Retirements (GW)', 'sheet_name':'ret_ann_psh', 'result': 'Annual Retirements BA (GW)', 'preset': 'Stacked Bars Cumulative',
    #  'config':{
    #      'series':'rb',
    #      'filter':{'tech':['Pumped-Hydro'],}}
    # }, 
]
