## ReEDS
**Regional Energy Deployment System (ReEDS) Model**

 
[![CI](https://github.com/ReEDS-Model/ReEDS/actions/workflows/python-app.yaml/badge.svg?branch=main)](https://github.com/ReEDS-Model/ReEDS/actions/workflows/python-app.yaml)
[![Documentation](https://img.shields.io/badge/Documentation-view%20online-0a7f5e?logo=readthedocs&logoColor=white&labelColor=555)](https://reeds-model.github.io/ReEDS)
![Static Badge](https://img.shields.io/badge/python-3.11-blue)
![GitHub License](https://img.shields.io/github/license/ReEDS-Model/ReEDS)
[![DOI](https://zenodo.org/badge/189060033.svg)](https://doi.org/10.5281/zenodo.16943302)

</br>
</br>

This GitHub repository contains the source code for NLR's ReEDS model.
The ReEDS model source code is available at no cost from the National Laboratory of the Rockies.
The ReEDS model can be downloaded or cloned from [https://github.com/ReEDS-Model/ReEDS](https://github.com/ReEDS-Model/ReEDS).

If you want to use the latest stable version of ReEDS, download or check out the latest stable release [here](https://github.com/ReEDS-Model/ReEDS/releases/latest).

**For more information about the model, see the [ReEDS Documentation](https://reeds-model.github.io/ReEDS).**

ReEDS training videos are available on the [NLR Learning YouTube channel](https://youtube.com/playlist?list=PLmIn8Hncs7bG558qNlmz2QbKhsv7QCKiC&si=NgGBaL_MxNcYiIEX).



<a name="Introduction"></a>

## Introduction

[ReEDS](https://www.nlr.gov/analysis/reeds/) is a capacity planning and dispatch model for the U.S. electricity system.

As NLR's flagship long-term power sector model, ReEDS has served as the primary analytic tool for [many studies](https://reeds-model.github.io/ReEDS/publications.html) of electricity sector research questions.
Example model results are available in the [Scenario Viewer](https://scenarioviewer.nlr.gov/).




<a name="Software"></a>

## Quick-start guide

The ReEDS model is written in [Python](https://www.python.org/), [GAMS](https://www.gams.com/), and [Julia](https://julialang.org/).
Python and Julia are free, open-source languages;
GAMS requires a software license from the vendor.
A step-by-step guide for getting started with ReEDS is available [here](https://reeds-model.github.io/ReEDS/setup.html), and a quick-start guide for advanced users is outlined below.

1. Install Python using the Anaconda Distribution: <https://www.anaconda.com/download/success>
2. Set up GAMS:
    1. Install GAMS: <https://www.gams.com/download/>
    2. Obtain a combined GAMS/CPLEX license: <https://www.gams.com/sales/licensing/>
        1. Small ReEDS systems have been solved using the open-source [COIN-OR](https://www.coin-or.org/) solver as described [here](https://www.nlr.gov/docs/fy21osti/77907.pdf), but this capability is not actively maintained.
        2. Other commercial solvers have also been successfully applied to ReEDS, but setup details and some solver tuning are specific to the CPLEX solver.
3. Install Julia version 1.12.1 as described in the [documentation](https://reeds-model.github.io/ReEDS/setup.html#reeds2pras-julia-and-stress-periods-setup):
    1. Follow the platform-dependent installation instructions at <https://julialang.org/downloads/> to install both `julia` and `juliaup`
    2. Specify version 1.12.1 by running:
        1. `juliaup add 1.12.1`
        2. `juliaup default 1.12.1`
4. Open a command-line interface and set up your environments:
    1. Clone the ReEDS repository: `git clone git@github.com:ReEDS-Model/ReEDS.git` or `git clone https://github.com/ReEDS-Model/ReEDS.git`
    2. Navigate to the cloned repository
    3. Create the `reeds2` [conda environment](https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html): `conda env create -f environment.yml`
    4. Activate the `reeds2` environment: `conda activate reeds2`
    5. Instantiate the Julia environment: `julia --project=. instantiate.jl`
    6. (Optional) Several large data files are hosted remotely.
    These files are downloaded automatically as needed during a ReEDS run, but to finish all the internet-requiring steps up front, you can download them all by running `python reeds/remote.py`.
    Additional details on remote files and other topics can be found in the [user guide](https://reeds-model.github.io/ReEDS/user_guide.html#large-input-files).
5. Run ReEDS on a test case from the root of the cloned repository:
    1. For interactive setup: `python runreeds.py`
    2. For one-line operation: `python runreeds.py -b v20250314_main -c test`.
    In this example, "v20250314_main" is the prefix for this batch of cases, and "test" is the suffix of the cases file, in this case `cases_test.csv`, located in the root of the repository.
    Run `python runreeds.py -h` for information on other optional command-line arguments for ReEDS.




<a name="Contact"></a>

## Contact Us

If you have comments and/or questions, you can contact the ReEDS team at [ReEDS.Inquiries@nlr.gov](mailto:ReEDS.Inquiries@nlr.gov) or post a question on the [discussion pages](https://github.com/ReEDS-Model/ReEDS/discussions).
