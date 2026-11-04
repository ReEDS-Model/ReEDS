#%% Imports
import sys
import copy
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import reeds


#%% Specially processed inputs
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


#%% Results container
SPECIAL = {
    'sw': reeds.io.get_switches,
    'hierarchy': reeds.io.get_hierarchy,
    'dfmap': reeds.io.get_dfmap,
    'county2zone': reeds.io.get_county2zone,
    'inflatable': reeds.io.get_inflatable,
    'demand_rt': get_demand_rt,
    'capcost': get_capcost,
    'supplycurve': get_supplycurve,
    'npv': get_npv,
    'scoe': get_scoe,
}

class ReEDScase:
    """A completed ReEDS run"""
    def __init__(self, casepath:str|Path, verbose=0):
        self.casepath = Path(reeds.io.standardize_case(casepath))
        self.verbose = verbose
        self.inputs = {}
        self.outputs = {}

    def __getattr__(self, name):
        if name in SPECIAL:
            if name not in self.inputs:
                value = SPECIAL[name](self.casepath)
                self.inputs[name] = value
                setattr(self, name, value)
            return self.inputs[name]
        elif name not in self.outputs:
            if self.verbose:
                print(f'Loading {name}')
            ## Try outputs first
            try:
                value = reeds.io.read_output(self.casepath, filename=name)
                self.outputs[name] = value
                setattr(self, name, value)
            ## Then inputs
            except (KeyError, FileNotFoundError):
                try:
                    value = reeds.io.read_input(self.casepath, name=name)
                    self.inputs[name] = value
                    setattr(self, name, value)
                except FileNotFoundError:
                    err = f"'{name}' is neither an input nor an output of {self.casepath}"
                    raise KeyError(err)
            return value
        else:
            return getattr(self, name)

    def copy(self, deep=True):
        if deep:
            return copy.deepcopy(self)
        else:
            return copy.copy(self)
