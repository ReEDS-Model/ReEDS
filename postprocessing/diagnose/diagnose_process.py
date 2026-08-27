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
    subprocess.check_call([sys.executable, "-m", "pip", "install", "gamsapi[transfer]==45.1.0"])

## Import packages
import pathlib
import os
import re
import pandas as pd
import numpy as np
import h5py
import gams.transfer as gt
from gams.core import gdx
import argparse
import matplotlib.pyplot as plt

###########
#%% Helper functions
def df_to_h5(df, path, groupname="data", tablename="table"):
    """Write a DataFrame to an HDF5 file as a single structured table dataset,
    so each row keeps its columns (e.g. 'i' and 'value') together as one
    record. This lets the file be filtered directly, e.g.:

        import h5py, pandas as pd
        t = h5py.File(path, "r")[groupname][tablename][:]
        t[t["value"] < 0]              # boolean filter, all columns stay aligned
        pd.DataFrame(t)                 # or load as a DataFrame (decode bytes columns after)
    """
    dtype_fields = []
    arrays = {}
    for col in df.columns:
        values = df[col].to_numpy()
        if values.dtype == object or values.dtype.kind in ("U", "S"):
            arrays[col] = np.array([str(v) for v in values], dtype=object)
            dtype_fields.append((str(col), h5py.string_dtype(encoding="utf-8")))
        else:
            arrays[col] = values
            dtype_fields.append((str(col), values.dtype))

    structured = np.zeros(len(df), dtype=dtype_fields)
    for col in df.columns:
        structured[str(col)] = arrays[col]

    with h5py.File(path, "w") as f:
        grp = f.create_group(groupname)
        grp.create_dataset(tablename, data=structured)

###########
#%% Main functionality
class Analyzer:
    def __init__(self, file):
        self.file = file
        self.matrix = None
        self.rhs = None

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
        gdx.gdxLibraryUnload()

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

        m.read(file, records=False)
        if set(known_symbols) != set(m.listSymbols()):
            raise Exception(
                "GDX file seems to be from CONVERT but found missing or unexpected symbols..."
            )

        # set
        self._file = file
        
    # The definition is used to load the matrix by equations (i) and variables (j), 
    # along with their real and absolute values, as well as their counts.
    def loadMatrix(self):
        m = gt.Container(self.file)

        eq_map = dict(zip(*[m["i"].records[x] for x in m["i"].records.columns]))
        var_map = dict(zip(*[m["j"].records[x] for x in m["i"].records.columns]))

        df = m["A"].records
        df["i"] = df["i"].map(eq_map)
        df["i_block"] = df["i"].str.split("(").str[0]
        df["j"] = df["j"].map(var_map)
        df["j_block"] = df["j"].str.split("(").str[0]

        df["abs(value)"] = df["value"].abs()
        df["count"] = 1

        df = df[["i", "i_block", "j", "j_block", "value", "abs(value)", "count"]]
        df["i"] = df["i"].astype(object)
        df["j"] = df["j"].astype(object)
        df["i_block"] = df["i_block"].astype(object)
        df["j_block"] = df["j_block"].astype(object)

        self.matrix = df
        
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
            return self.matrix.groupby("j")["count"].sum().reset_index(drop=False)

        if by == "block":
            return (
                self.matrix[["i_block", "j", "count"]]
                .groupby(["i_block", "j"])
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
            line = file.readline()

        if "convert" not in line.casefold():
            raise Exception(
                "The scalar_model_file was not generated by CONVERT, "
                "must pass a model file generated by CONVERT to get the RHS"
            )

        with open(scalar_model_file, "r") as file:
            contents = file.read()

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
            m.loadRHS(scalarmodel)
        #Collect the maximum and minimum RHS values along with their corresponding equation names, 
        #as well as the absolute maximum and the non-zero minimum values.          
        data=[max(self.rhs["value"]),min(self.rhs["value"]),
              self.rhs.loc[self.rhs[self.rhs["value"] == max(self.rhs["value"])].index[0],"i"],
              self.rhs.loc[self.rhs[self.rhs["value"] == min(self.rhs["value"])].index[0],"i"],
              max(self.rhs["value"].abs()),min(self.rhs["value"].abs()[self.rhs["value"].abs() > 0]),
              self.rhs.loc[self.rhs[self.rhs["value"].abs() == max(self.rhs["value"].abs())].index[0], "i"],
              self.rhs.loc[self.rhs[self.rhs["value"].abs() == min(self.rhs["value"].abs()[self.rhs["value"].abs() > 0])].index[0], "i"]
              ]  
        
        return data

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
    for gdxfile, scalarmodel in zip(gdxfiles, scalarmodels):
        print(f"Processing {gdxfile.name} and {scalarmodel.name}...")
        # create Analyzer object
        m = Analyzer(gdxfile)

        # Year tag
        tag = gdxfile.name.split("_")[1].split(".")[0]

        # Generate variable counts report
        var_count=m.countVariables()
        var_count["year"] = tag
        all_var_count.append(var_count)
        
        # Generate variable counts report by equation blocks
        if Sw_var_count_by_block==1:
            var_count_by_block=m.countVariables(by="block")
            var_count_by_block["year"] = tag
            df_to_h5(var_count_by_block, pathlib.Path(file_dir, f'var_count_by_block_{tag}.h5'))
        
        # Generate matrix statistics report
        describe_matrix=m.describeMatrix()
        describe_matrix.append(tag)
        all_describe_matrix.append(describe_matrix)
        
        # Export matrix
        if Sw_matrix==1:    
            matrix=m.matrix
            matrix["year"] = tag
            df_to_h5(matrix, pathlib.Path(file_dir, f'matrix{tag}.h5'), groupname='matrix')

        # Generate RHS statistics report

        describe_rhs  = m.describeRHS()
        describe_rhs.append(tag)  
        all_describe_rhs.append(describe_rhs)
        
        # Export RHS values
        if Sw_rhs == 1: 
            rhs=m.rhs
            rhs["year"] = tag
            df_to_h5(rhs, pathlib.Path(file_dir, f'rhs_{tag}.h5'), groupname='rhs')
    
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
        "describe_matrix.h5": all_describe_matrix,
        "describe_rhs.h5": all_describe_rhs,
        "var_count.h5": all_var_count}

    # Concatenate and export each dataframe
    for filename, data in output_data.items():
        print(filename)
        if "describe" not in filename:
            combined_data = pd.concat(data, ignore_index=True)
        else:
            combined_data=pd.DataFrame(data)
        df_to_h5(combined_data, pathlib.Path(file_dir, filename))
        
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
    