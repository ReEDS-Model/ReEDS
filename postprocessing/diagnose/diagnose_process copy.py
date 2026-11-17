###########
#%% IMPORTS
## Install GAMS API Package
import subprocess
import sys

try:
    import gams
    print("gamsapi is already installed.")
except ImportError:
    print("gamsapi is not installed. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "gamsapi[transfer]==51.3.0"])

## Import packages
import pathlib
import os
import re
import pandas as pd
import gams.transfer as gt
from gams.core import gdx
import argparse
import matplotlib.pyplot as plt
from concurrent.futures import ProcessPoolExecutor

###########
#%% Main functionality
class Analyzer:
    def __init__(self, file):
        self.file = file
        self.matrix = None
        self.rhs = None
        self._var_count_cache = None

    @property
    def file(self):
        return self._file

    @file.setter
    def file(self, file):
        if not isinstance(file, (os.PathLike, str)):
            raise TypeError(
                f"Argument 'file' expects type str or PathLike object, got {type(file)}"
            )

        file = pathlib.Path(file).expanduser().resolve()

        if not file.exists():
            raise Exception(
                f"GDX file '{os.fspath(file)}' does not exist, check spelling or path specification"
            )

        m = gt.Container()

        gdxHandle = gdx.new_gdxHandle_tp()
        _ = gdx.gdxCreateD(gdxHandle, m.system_directory, gdx.GMS_SSSIZE)
        _ = gdx.gdxOpenRead(gdxHandle, os.fspath(file))
        _, _, producer = gdx.gdxFileVersion(gdxHandle)

        if "convert" not in producer.casefold():
            raise Exception(
                f"GDX file was not produced by CONVERT, found producer: {producer}"
            )

        gdx.gdxClose(gdxHandle)
        gdx.gdxFree(gdxHandle)

        known_symbols = [
            "A",
            "ANl",
            "e",
            "i",
            "iobj",
            "j",
            "jb",
            "ji",
            "jobj",
            "js1",
            "js2",
            "jsc",
            "jsi",
            "objcoef",
            "objconst",
            "objjacval",
            "s",
            "x",
        ]

        m.read(file)
        if set(known_symbols) != set(m.listSymbols()):
            raise Exception(
                "GDX file seems to be from CONVERT but found missing or unexpected symbols..."
            )

        # set
        self._file = file
        self._container = m

    # The definition is used to load the matrix by equations (i) and variables (j),
    # along with their real and absolute values, as well as their counts.
    def loadMatrix(self):
        m = self._container

        eq_map = dict(zip(*[m["i"].records[x] for x in m["i"].records.columns]))
        var_map = dict(zip(*[m["j"].records[x] for x in m["i"].records.columns]))

        df = m["A"].records
        df["i"] = df["i"].map(eq_map)
        df["i_block"] = df["i"].str.split("(").str[0]
        df["j"] = df["j"].map(var_map)
        df["j_block"] = df["j"].str.split("(").str[0]

        df["abs(value)"] = df["value"].abs()
        df["count"] = 1

        self.matrix = df[["i", "i_block", "j", "j_block", "value", "abs(value)", "count"]]
        self._container = None
        
    # The definition is used to count variables either from the total or by equation blocks.
    def countVariables(self, by=None):
        if self.matrix is None:
            self.loadMatrix()

        if by is None:
            by = "none"

        if by not in {"none", "block"}:
            raise ValueError(
                "Argument 'by' can only take values: 'none', 'block', or None"
            )

        if by == "none":
            if self._var_count_cache is None:
                self._var_count_cache = self.matrix.groupby("j", observed=False)["count"].sum().reset_index(drop=False)
            return self._var_count_cache.copy()

        if by == "block":
            return (
                self.matrix[["i_block", "j", "count"]]
                .groupby(["i_block", "j"], observed=False)
                .sum()
                .reset_index(drop=False)
            )
            
    # The definition is used to identify variables that appear only once in the matrix.
    def findReportingVariables(self):
        count = self.countVariables()
        return count[count["count"] == 1]
    
    # The definition is used to count reporting variables.
    def countReportingVariables(self):
        return len(self.findReportingVariables())


    def findDenseColumns(self):
        if self.matrix is None:
            self.loadMatrix()

        var = self.matrix[["i", "j"]].groupby(["j"]).count()
        return var[var["i"] == len(self.matrix["i"].unique())].index.tolist()

    def countDenseColumns(self):
        return len(self.findDenseColumns())

    # The definition is used to collect matrix statistics.
    def describeMatrix(self):
        if self.matrix is None:
            self.loadMatrix()
        # number of reporting variables
        nrv = self.countReportingVariables()
        # number of equations
        rows = len(self.matrix["i"].unique())
        # number of variables
        cols = len(self.matrix["j"].unique())
        #number of non-zero elements in matrix
        nnz = len(self.matrix)

        # Create a list to store results, including:
        # - Number of equations, variables, and non-zero elements
        # - Maximum and minimum elements in the matrix
        # - Absolute maximum and minimum elements in the matrix, and their ratio
        # - Number of reporting variables, percentage of reporting variables in total variables,
        # - Ratio of reporting variables to non-zero elements
        data = [ rows,cols, nnz, max(self.matrix["value"]), min(self.matrix["value"]),
                max(self.matrix["abs(value)"]), min(self.matrix["abs(value)"]),
                max(self.matrix["abs(value)"]) / min(self.matrix["abs(value)"]), 
                nrv, nrv / cols * 100 , nrv / nnz * 100
                ]

        return data
    
    # The definition is used to load all rhs values.
    def loadRHS(self, scalar_model_file):
        if self.matrix is None:
            self.loadMatrix()

        scalar_model_file = pathlib.Path(scalar_model_file)
        with open(scalar_model_file, "r") as file:
            contents = file.read()

        if "convert" not in contents[:contents.index("\n")].casefold():
            raise Exception(
                "The scalar_model_file was not generated by CONVERT, "
                "must pass a model file generated by CONVERT to get the RHS"
            )

        pattern = re.compile(f"{re.escape(';')}(.*?)(?={re.escape(';')})", re.DOTALL)
        matches = re.findall(pattern, contents)

        lookfor = ["=E=", "=G=", "=L=", "=X=", "=N=", "=B=", "=C="]

        rhs = []
        for match in matches:
            match = match.replace("\n", "")
            for eq in lookfor:
                if eq in match:
                    parts = match.split(eq)
                    rhs.append(float(parts[-1].strip()))

        df = pd.DataFrame(self.matrix["i"].unique(), columns=["i"])
        df["value"] = rhs
        df["abs(value)"] = df["value"].abs()

        self.rhs = df
        
    # The definition is used to collect rhs statistics.
    def describeRHS(self):
        if self.rhs is None:
            raise ValueError("RHS not loaded; call loadRHS() first")
        rhs = self.rhs
        vals = rhs["value"]
        abs_vals = vals.abs()
        nonzero_mask = abs_vals > 0
        return [
            vals.max(), vals.min(),
            rhs.loc[vals.idxmax(), "i"], rhs.loc[vals.idxmin(), "i"],
            abs_vals.max(), abs_vals[nonzero_mask].min(),
            rhs.loc[abs_vals.idxmax(), "i"], rhs.loc[abs_vals[nonzero_mask].idxmin(), "i"],
        ]

def _process_year(args):
    gdxfile, scalarmodel, Sw_matrix, Sw_rhs, Sw_var_count_by_block = args
    m = Analyzer(gdxfile)
    tag = gdxfile.name.split("_")[1].split(".")[0]

    result = {}
    result["var_count"] = m.countVariables()
    result["var_count"]["year"] = tag

    if Sw_var_count_by_block == 1:
        result["var_count_by_block"] = m.countVariables(by="block")
        result["var_count_by_block"]["year"] = tag

    if Sw_matrix == 1:
        result["matrix"] = m.matrix.copy()
        result["matrix"]["year"] = tag

    describe_matrix = m.describeMatrix()
    describe_matrix.append(tag)
    result["describe_matrix"] = describe_matrix

    if Sw_rhs == 1:
        m.loadRHS(scalarmodel)
        result["rhs"] = m.rhs.copy()
        result["rhs"]["year"] = tag

    describe_rhs = m.describeRHS()
    describe_rhs.append(tag)
    result["describe_rhs"] = describe_rhs

    return result


#%%
if __name__ == "__main__":

    #Argument inputs
    parser = argparse.ArgumentParser(
        description="Model Size by year - Number of equations and variables",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--casepath", "-n", type=str, default=""
                        , help="case path")
    parser.add_argument("--year", "-y", type=str, default="0"
                        , help="get diagnose results for all years or single year")
    parser.add_argument("--GSw_matrix", "-sw_m", type=int , default="0"
                        , help="get matrix value")
    parser.add_argument("--GSw_rhs", "-sw_r", type=int , default="0"
                        , help="get rhs value")
    parser.add_argument("--GSw_var_count_by_block", "-sw_var_block", type=int , default="0"
                        , help="get variable count by block")

    args = parser.parse_args()
    casepath = args.casepath
    year= args.year
    Sw_matrix = args.GSw_matrix
    Sw_rhs = args.GSw_rhs
    Sw_var_count_by_block=args.GSw_var_count_by_block
    #%% Inputs for testing
    #casepath = ''
    #year= 2023
    #Sw_matrix = 0
    #Sw_rhs = 1
    #Sw_var_count_by_block=1
    
    #%%### GDX and Scalar Inputs 
    file_dir = pathlib.Path(casepath, "outputs", "model_diagnose")

    # Get directory list of gdx and scalar files
    scalarmodels = list(pathlib.Path(file_dir).glob("scalar_model*.gms"))
    gdxfiles = list(pathlib.Path(file_dir).glob("reeds*.gdx"))

    scalarmodels.sort()
    gdxfiles.sort()
    
    # The number of gdx files should be eqaul to number of scalar files.
    assert len(gdxfiles) == len(scalarmodels)
    # If the year switch is not zero, the GDX and scalar directory list is filtered
    # by the corresponding year.
    if year!='0':
        scalarmodels = list(pathlib.Path(file_dir).glob("scalar_model_{}.gms".format(year)))
        gdxfiles = list(pathlib.Path(file_dir).glob("reeds_{}.gdx".format(year)))
        if not gdxfiles:
            available = sorted(p.stem.split("_")[1] for p in pathlib.Path(file_dir).glob("reeds_*.gdx"))
            raise FileNotFoundError(
                f"No GDX file found for year {year}. Available years: {available}"
            )

    # Create lists for combined data
    all_describe_rhs= []
    all_describe_matrix= []
    all_var_count= []
    
    if Sw_matrix==1:
        all_matrix = []

    if Sw_rhs == 1:
        all_rhs = []

    if Sw_var_count_by_block==1:
        all_var_count_by_block= []
        
    # Generate diagnosis reports for the year found in the directory list.
    args_list = [
        (gdxfile, scalarmodel, Sw_matrix, Sw_rhs, Sw_var_count_by_block)
        for gdxfile, scalarmodel in zip(gdxfiles, scalarmodels)
    ]
    with ProcessPoolExecutor() as executor:
        year_results = list(executor.map(_process_year, args_list))

    for res in year_results:
        all_var_count.append(res["var_count"])
        all_describe_matrix.append(res["describe_matrix"])
        all_describe_rhs.append(res["describe_rhs"])
        if Sw_var_count_by_block == 1:
            all_var_count_by_block.append(res["var_count_by_block"])
        if Sw_matrix == 1:
            all_matrix.append(res["matrix"])
        if Sw_rhs == 1:
            all_rhs.append(res["rhs"])
        
    
    # Convert the `all_describe_rhs` and `all_describe_matrix` lists to data frames 
    # with their corresponding column names.
    all_describe_rhs=pd.DataFrame(all_describe_rhs, 
            columns=('max','min','equation_max','equation_min','absolute_max',
                    'absolute_min(non-zero)','equation_absolute_max',
                    'equation_absolute_min(non-zero)','year'))
    all_describe_matrix=pd.DataFrame(all_describe_matrix,
            columns=('rows', 'cols', 'nnz', 'max', 'min', 'max(abs)', 'min(abs)',
                     'max(abs) / min(abs)', 'n_reporting_variables', 'n_reporting_variables (%col)',
                     'n_reporting_variables (%nnz)','year'))
    
    # Define dataframes and their corresponding output filenames
    output_data = {
        "describe_matrix.csv": all_describe_matrix,
        "describe_rhs.csv": all_describe_rhs,
        "var_count.csv": all_var_count}

    if Sw_matrix==1:
        output_data["matrix.csv"] = all_matrix
    if Sw_rhs==1:
        output_data["rhs.csv"] = all_rhs
    if Sw_var_count_by_block==1:
        output_data["var_count_by_block.csv"] = all_var_count_by_block
        
    # Concatenate each dataframe and export them all as separate keys in a single HDF5 file
    h5_path = pathlib.Path(file_dir, "diagnose_output.h5")
    with pd.HDFStore(h5_path, mode="w") as store:
        for filename, data in output_data.items():
            key = pathlib.Path(filename).stem
            print(key)
            if "describe" not in filename:
                combined_data = pd.concat(data, ignore_index=True)
            else:
                combined_data = pd.DataFrame(data)
            store.put(key, combined_data, format="table", data_columns=True)
        
    # Plot a histogram of variable counts.
    all_var_count=pd.concat(all_var_count, ignore_index=True)
    for year in all_var_count['year'].unique():
        df=all_var_count[all_var_count["year"] == year]
        plt.hist(df['count'], bins=range(0, 200), edgecolor='black')
        plt.xlabel('Number of Nonzeros')
        plt.ylabel('Number of Columns')
        plt.title('Histogram of Nonzeros in Columns')
        plt.savefig(pathlib.Path(file_dir, f'reeds_{year}.png'))
        plt.close()
    