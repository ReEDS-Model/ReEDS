import os
import sys
import pandas as pd
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds

def test_output_files(casepath):
    outputs_folder = os.path.join(casepath, 'outputs')
    report_params_path = os.path.join(casepath, 'reeds', 'core', 'terminus', 'report_params.csv')
    lastyear = reeds.io.get_years(casepath)[-1]

    # each parameter in report_params.csv should be associated with an output csv file
    report_params = pd.read_csv(report_params_path, comment='#')
    report_params['fpath'] = report_params.param.map(lambda x: x.split('(')[0])
    # rename outputs as specified by output_rename column
    rename = report_params.loc[
        ~report_params.output_rename.isnull()
    ].set_index('fpath').output_rename.to_dict()
    report_params['fpath'] = report_params['fpath'].replace(rename) + '.csv'

    # Include additional files in outputs folder that should be generated for each run
    expected_plots = [
        # Static plots (single_case_plots.py)
        os.path.join('figures', i) + '.png' for i in [
            'bars_retirements_additions',
            'inputs_cfmap-upv',
            f'plot_dispatch-weightwidth-{lastyear}',
        ]
    ]

    expected_files = (
        report_params.fpath.tolist()
        + [
            # Standard bokeh outputs (postprocessing/bokehpivot)
            os.path.join('reeds-report', 'report.html'),
            os.path.join('reeds-report', 'report.xlsx'),
            # Health damages (health_damage_calculations.py)
            'health_damages_caused_r.csv',
            # Retail rates (retail_rate_calculations.py)
            os.path.join('retail', 'retail_rate_components.csv'),
        ]
        + expected_plots
    )

    missing_files = [
        filename for filename in expected_files
        if not os.path.exists(os.path.join(outputs_folder, filename))
    ]

    assert (len(missing_files) == 0), f"Missing {len(missing_files)} output files: {missing_files}"
