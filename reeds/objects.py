### Imports
import sys
import copy
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import reeds


### Specially processed inputs
def get_demand_rt(case):
    """Get exogenous electricity demand by region and year [TWh]"""
    numhours = (
        reeds.io.read_input(case, ('rep', 'numhours'))
        .rename(columns={'*h':'h'}).set_index('h').squeeze(1)
    )
    df = (
        reeds.io.read_input(case, ('rep', 'load_allyear'))
        .rename(columns={'*r':'r'})
    )
    df.MW = df.MW * df.h.map(numhours)
    df = df.groupby(['r','t']).MW.sum().rename('TWh') / 1e6
    return df


def get_capcost(case):
    """Get capital cost by technology and year [$/kW]"""
    df = (
        reeds.io.read_input(case, 'plantcharout')
        .set_index(['variable','*i','t'])
        .loc['capcost'].value.unstack('*i').rename_axis('i', axis=1)
        / 1e3
    )
    df.columns = df.columns.str.lower()
    return df


def get_supplycurve(case):
    """Get supply curve used in the optimization [GW]"""
    df = (
        reeds.io.read_input(case, 'rsc_combined')
        .rename(columns={'*i':'i'}).set_index('sc_cat').loc['cap']
        .groupby(['i','r']).value.sum()
        / 1e3
    ).reset_index()
    df['i'] = df['i'].str.strip('_0123456789')
    df = df.groupby(['i','r']).value.sum()
    return df


def get_npv(case, val2sheet=None):
    """Get net present value of system cost [$B]"""
    df = (
        reeds.io.read_report(case, 'Present Value of System Cost', val2sheet)
        .set_index('cost_cat')['Discounted Cost (Bil $)']
    ).rename('billionUSD')
    return df


def get_scoe(case, val2sheet=None):
    """Get system cost of electricity [$/MWh]"""
    df = (
        reeds.io.read_report(case, 'National Average Electricity', val2sheet)
        .pivot(index='year', columns='cost_cat', values='Average cost ($/MWh)').fillna(0)
    )
    return df


### Function holders
SPECIAL_INPUTS = {
    'sw': reeds.io.get_switches,
    'hierarchy': reeds.io.get_hierarchy,
    'dfmap': reeds.io.get_dfmap,
    'county2zone': reeds.io.get_county2zone,
    'inflatable': reeds.io.get_inflatable,
    'demand_rt': get_demand_rt,
    'capcost': get_capcost,
    'supplycurve': get_supplycurve,
}

SPECIAL_OUTPUTS = {
    'npv': get_npv,
    'scoe': get_scoe,
}


### Results container
class ReEDScase:
    """
    Input/output data handler for a completed ReEDS run.

    Parameters
    ----------
    casepath : str or path object
        A filepath to a completed ReEDS run (e.g. `/path/to/ReEDS/runs/casename`).
        If the provided filepath ends in `inputs_case`, it will be stripped off to
        leave the parent run directory name.

    Usage
    -----
    After initializing the object (for example, as `case = reeds.ReEDScase(casepath)`),
    the following parameters become available (typically in `pd.DataFrame` or
    `pd.Series` format) via top-level attributes:
    - Any output parameter available from `reeds.io.read_output()` listed in
      `reeds/core/terminus/report_params.csv`
    - Any input parameter available as a csv file in `casepath/inputs_case` or in
      `casepath/inputs_case/inputs.h5` via `reeds.io.read_input()`
    - The following specially handled files:
        - Inputs:
            - `'sw'`: Switch values
            - `'hierarchy'`: Region hierarchy
            - `'dfmap'`: Dictionary of `gpd.GeoDataFrame`s of region hierarchy levels
            - `'county2zone'`: County-to-zone mapping
            - `'inflatable'`: Dictionary of inflation adjustors between pairs of years
            - `'demand_rt'`: Annual electricity demand by model zone and year
            - `'capcost'`: Generation technology capital cost in ReEDS `dollar_year` USD
            - `'supplycurve'`: Available generation capacity for supply-curve technologies
              by model zone
        - Outputs:
            - `'npv'`: Net present value of total system costs [$billion] from bokehpivot
              in `postprocessing.bokehpivot.defaults.DEFAULT_DOLLAR_YEAR` USD
            - `'scoe'`: System cost of electricity [$/MWh] from bokehpivot
              in `postprocessing.bokehpivot.defaults.DEFAULT_DOLLAR_YEAR` USD

    The series/dataframe for a parameter is not loaded until the parameter is called.
    Once its parameter is called, the dataset is stored within the instantiated ReEDScase
    object, so subsequent calls will be faster than the first.

    Examples
    --------

    First initialize the object:
    >>> import reeds
    >>> case = reeds.ReEDScase('/path/to/ReEDS/runs/casename'/)

    Capacity by technology, region, and year:
    >>> case.cap
    i                      r     t   
    nuclear                CA_S  2010    2240.000000
                                 2015    2240.000000
                                 2020    2240.000000
                                 2025    2240.000000
                           WA_E  2010    1151.000000
                                            ...     
    Gas-CC_Gas-CC-CCS_mod  OR_E  2035    1272.302612
                           OR_W  2030     380.336029
                                 2035     392.200012
                           WA_W  2030    1176.600830
                                 2035    1176.600830
    Name: Value, Length: 881, dtype: float32

    Switch values:
    >>> case.sw
    AWS                                                                  0
    GSw_AVG_iter                                                         1
    GSw_AnnualCap                                                        0
    GSw_AnnualCapScen                                              default
    GSw_BECCS                                                            1
                                               ...                        
    threads                                                              4
    casedir              /Users/pbrown/github/ReEDS/runs/v20261026_main...
    reeds_path                                  /Users/pbrown/github/ReEDS
    hoursperperiod                                                      24
    periodsperyear                                                     365
    Length: 430, dtype: object

    Annual generation by technology and year:
    >>> (case.gen_h * case.hours).groupby(['i','t']).sum()
    i           t   
    CoalOldScr  2010    13286415.00
                2015    12660082.00
                2020     2350105.50
                2025     2229765.25
    CoalOldUns  2010     1521479.00
                           ...     
    wind-ons_9  2015     3869042.50
                2020     3751190.75
                2025     4271446.00
                2030     5036149.50
                2035     7822835.00
    Name: Value, Length: 219, dtype: float32

    After a parameter is loaded for the first time, it is stored in the object
    and does not need to be read again, reducing access time.

    First call:
    >>> %time case.scoe
    CPU times: user 190 ms, sys: 30 ms, total: 220 ms
    Wall time: 261 ms

    Second call:
    >>> %time case.scoe
    CPU times: user 3 μs, sys: 0 ns, total: 3 μs
    Wall time: 6.2 μs

    The parameters that have been loaded so far are available in the `.inputs`
    and `.outputs` attributes:
    >>> print(case.inputs.keys())
    dict_keys(['sw'])

    >>> print(case.outputs.keys())
    dict_keys(['cap', 'gen_h', 'hours', 'scoe'])

    (`hours` includes dynamic stress periods, so it is an output rather than an input;
    the input representative-period hours can be accessed via the usual
    `reeds.io.read_input(case.casepath, ('rep', 'numhours'))`.)
    """
    def __init__(self, casepath:str|Path, verbose=0):
        self.casepath = Path(reeds.io.standardize_case(casepath))
        self.verbose = verbose
        self.inputs = {}
        self.outputs = {}

    def __getattr__(self, name):
        if name in SPECIAL_INPUTS:
            if name not in self.inputs:
                df = SPECIAL_INPUTS[name](self.casepath)
                self.inputs[name] = df
                setattr(self, name, df)
            return self.inputs[name]
        elif name in SPECIAL_OUTPUTS:
            if name not in self.outputs:
                df = SPECIAL_OUTPUTS[name](self.casepath)
                self.outputs[name] = df
                setattr(self, name, df)
            return self.outputs[name]
        elif name not in self.outputs:
            if self.verbose:
                print(f'Loading {name}')
            ## Try outputs first
            try:
                df = reeds.io.read_output(self.casepath, filename=name)
                ## If in long format, convert to a multiindex series
                if 'Value' in df:
                    index = [c for c in df if c != 'Value']
                    df = df.set_index(index).squeeze(1)
                self.outputs[name] = df
                setattr(self, name, df)
            ## Then inputs
            except (KeyError, FileNotFoundError):
                try:
                    df = reeds.io.read_input(self.casepath, name=name)
                    self.inputs[name] = df
                    setattr(self, name, df)
                except FileNotFoundError:
                    err = f"'{name}' is neither an input nor an output of {self.casepath}"
                    raise KeyError(err)
            return df
        else:
            return getattr(self, name)

    def copy(self, deep=True):
        if deep:
            return copy.deepcopy(self)
        else:
            return copy.copy(self)
