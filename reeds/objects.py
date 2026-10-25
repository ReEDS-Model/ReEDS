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


#%% Results container
SPECIAL = {
    'sw': reeds.io.get_switches,
    'hierarchy': reeds.io.get_hierarchy,
    'dfmap': reeds.io.get_dfmap,
    'county2zone': reeds.io.get_county2zone,
    'inflatable': reeds.io.get_inflatable,
    'demand_rt': get_demand_rt,
}

class ReEDScase:
    """A completed ReEDS run"""
    def __init__(self, casepath:str|Path, verbose=0):
        self.casepath = Path(reeds.io.standardize_case(casepath))
        self.verbose = verbose
        self.inputs = {}
        self.outputs = {}

    # def get_status(self):
    #     ...

    # def get_results(self):
    #     ...

    # def result(self, filename:str):
    #     """
    #     """
    #     if filename in self.outputs:
    #         return self.outputs[filename]
    #     else:
    #         return reeds.io.read_output(self.casepath, filename=filename)

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
                    # err = (
                    #     f"'{name}' is neither an input nor an output of this ReEDS run. "
                    #     f'Check to make sure it finished: {self.casepath}'
                    # )
                    err = f"'{name}' is neither an input nor an output of {self.casepath}"
                    raise KeyError(err)
            return value
        else:
            return getattr(self, name)
            # return self.outputs[name]

    def copy(self, deep=True):
        if deep:
            return copy.deepcopy(self)
        else:
            return copy.copy(self)


# #%% Test
# casepath = '/Users/pbrown/github/ReEDS/runs/v20261008_chM0_Pacific'
# foo = ReEDScase(casepath)

# #%%
# foo.cap
# foo.gen_h

# # # %time foo.capacity_offline
# # %timeit foo.reqt_quant
# foo.capacity_offline
# # foo.barf
# foo.tsc_forward

# foo.hierarchy
# foo.dfmap['r']

# print(f'inputs: {foo.inputs.keys()}')
# print(f'outputs: {foo.outputs.keys()}')

# #%%
# foo.barf
