# Getting Started 
The ReEDS model source code is available at no cost from the National Laboratory of the Rockies (NLR). The ReEDS model can be downloaded or cloned from [https://github.com/ReEDS-Model/ReEDS](https://github.com/ReEDS-Model/ReEDS).

New users may also wish to start with some ReEDS training videos which are available on the [NLR YouTube channel](https://youtu.be/aGj3Jnspk9M?si=iqCRNn5MbGZc8ZIO).


## Installation Guide
### Windows Command Line
The setup and execution of the ReEDS model can be accomplished using a command-line interpreter application and launching a command line interface (referred to as a "terminal window" in this documentation). For example, initiating the Windows Command Prompt application, i.e., cmd.exe, will launch a terminal window {numref}`figure-windows-command-prompt`. (Note: If you encounter issues using command prompt, try using anaconda prompt or a git bash window)

```{figure} figs/readme/cmd-prompt.png
:name: figure-windows-command-prompt

Screenshot of a Windows Command Prompt terminal window
```

**SUGGESTION:** use a command line emulator such as ConEmu ([https://conemu.github.io/](https://conemu.github.io/)) for a more user-friendly terminal. The screenshots of terminal windows shown in this document are taken using ConEmu.

**IMPORTANT:** Users should exercise Administrative Privileges when installing software. For example, right click on the installer executable for one of the required software (e.g., Anaconda3-2019.07-Windows-x86\_64.exe) and click on "Run as administrator" ({numref}`figure-run-as-admin`). Alternatively, right click on the executable for the command line interface (e.g., Command Prompt) and click on "Run as administrator" ({numref}`figure-run-as-admin-2`). Then run the required software installer executables from the command line.

```{figure} figs/readme/run-as-admin.png
:name: figure-run-as-admin

Screenshot of running an installer executable using "Run as administrator"
```

```{figure} figs/readme/run-as-admin-2.png
:name: figure-run-as-admin-2

Screenshot of running "Command Prompt" with "Run as administrator"
```

### Python Configuration
`````{tab-set}
````{tab-item} Windows
Install Anaconda: [https://www.anaconda.com/download](https://www.anaconda.com/download).

**IMPORTANT** : Be sure to download the Windows version of the installer.

Add Python to the "path" environment variable:

1. In the Windows start menu, search for "environment variables" and click "Edit the system environment variables" ({numref}`figure-search-env-var`). This will open the "System Properties" window ({numref}`figure-sys-prop-win`).

```{figure} figs/readme/search-env-var.png
:name: figure-search-env-var

Screenshot of a search for "environment variables" in the Windows start menu
```

```{figure} figs/readme/sys-prop-win.png
:name: figure-sys-prop-win

Screenshot of the "System Properties" window.
```


2. Click the "Environment Variables" button on the bottom right of the window ({numref}`figure-sys-prop-win`). This will open the "Environment Variables" window ({numref}`figure-env-var-wind`).


```{figure} figs/readme/env-var-win.png
:name: figure-env-var-wind

Edit the Path environment variable
```


3. Highlight the Path variable and click "Edit" ({numref}`figure-env-var-wind`). This will open the "Edit environment variable" window ({numref}`figure-edit-env-var-win`).

```{figure} figs/readme/edit-env-var-win.png
:name: figure-edit-env-var-win

Append the Path environment
```


4. Click "New" ({numref}`figure-edit-env-var-win`) and add the directory locations for \Anaconda\ and \Anaconda\Scripts to the environment path.

**IMPORTANT** : Test the Python installation from the command line by typing "python" (no quotes) in the terminal window. The Python program should initiate ({numref}`figure-python-test`).

```{figure} figs/readme/py-test.png
:name: figure-python-test

Screenshot of a test of Python in the terminal window
```
````

````{tab-item} macOS / Linux
Download the latest version of Anaconda: [https://www.anaconda.com/download](https://www.anaconda.com/download)

During Installation, select to install Anaconda for your machine only.

```{figure} figs/readme/anaconda-install-mac.png
:name: figure-anaconda-install-mac

Image of Anaconda Install Mac
```

To have the installer automatically add anaconda to PATH, ensure that you've selected the box to "Add conda initialization to the shell"

```{figure} figs/readme/anaconda-custom-install-mac.png
:name: figure-anaconda-custom-install-mac

Image of Anaconda Install Mac - Customize Installation Type
```

**To validate Python was installed properly** execute the following command from a new terminal (without quotes): "python"

Python should initiate ({numref}`figure-python-test2`).

```{figure} figs/readme/py-test.png
:name: figure-python-test2

Screenshot of a test of Python in the terminal window
```

````
`````

#### Conda Environment Setup

It is highly recommended to run ReEDS using the conda environment provided in the repository. This environment (named `reeds2`) is specified by the `environment.yml` and can be built with the following command - make sure you navigate to the ReEDS repository from terminal first: 

```
conda env create -f environment.yml
```

You can verify that the environment was successfully created using the following (you should see `reeds2` in the list):

```
conda env list
```

When creating the reeds2 environment locally, you might run into an SSL error that looks like: `CondaSSLError: Encountered an SSL error. Most likely a certificate verification issue.` To resolve this issue, run the following command before creating the environment again: `conda config --set ssl_verify false`.


### GAMS Configuration
NLR uses GAMS versions 51.3.0 and 49.6.0; however, older versions might also work. A valid GAMS license must be installed.

For more information on getting a trial license for GAMS, see the [FAQ](faq.md#table-of-contents)

1. Install GAMS: [https://www.gams.com/download/](https://www.gams.com/download/)
    
    
    **If installing on Mac:** on the "Installation" page, click "customize" and ensure the box to "Add GAMS to PATH" is checked.

    ```{figure} figs/readme/gams-install-mac.png
    :name: figure-gams-install-mac

    Image of GAMS Install Mac
    ```

2. Add GAMS to the PATH environment variable. **This step can be skipped if you're on Mac and added GAMS to the path in step 1.**
   1. Follow the same instructions for adding Python to the path in the [Python Configuration](#python-configuration) section above. Append the environment path with the directory location for the _gams.exec_ application (e.g., C:\GAMS\win64\34).

3. Test the GAMS installation from the command line by typing `gams`. The GAMS program should initiate ({numref}`figure-gams-test`).

```{figure} figs/readme/gams-test.png
:name: figure-gams-test

Screenshot of a test of GAMS from the terminal window
```

### Repository Setup
The ReEDS source code is hosted on GitHub at <https://github.com/ReEDS-Model/ReEDS>.

1. Install Git Large File Storage, instructions can be found here: [Installing Git Large File Storage](https://docs.github.com/en/repositories/working-with-files/managing-large-files/installing-git-large-file-storage)

2. From the Git command line run the following command to enable large file storage.
```
git lfs install
```

3. Clone the ReEDS repository on your desktop or download a ZIP from GitHub.

### ReEDS2PRAS, Julia, and Stress Periods Setup
Julia will need to be installed and set up to successfully run the model since ReEDS uses stress periods by default. The recommended way to install Julia is via **juliaup**, the official Julia version manager, which makes it easy to install and switch between specific Julia versions. Julia `1.12.1` is the currently tested version across all platforms.

#### Step 1: Install juliaup

`````{tab-set}
````{tab-item} Windows
Install juliaup using `winget` from a terminal (Command Prompt or PowerShell):

    winget install --id Julialang.juliaup

Alternatively, install from the [Microsoft Store](https://www.microsoft.com/store/apps/9NJNWW8PVKMN).
````

````{tab-item} macOS / Linux
Run the following command from a terminal:

    curl -fsSL https://install.julialang.org | sh

Follow the on-screen prompts. When installation is complete, open a new terminal session (or run `source ~/.bashrc` / `source ~/.zshrc`) so that `juliaup` is available on your PATH.

macOS and Linux users can also install via Homebrew:

    brew install juliaup
````
`````

Verify the installation was successful:
```
juliaup status
```

#### Step 2: Install and pin the tested Julia version

Install Julia `1.12.1` and set it as the default:
```
juliaup add 1.12.1
juliaup default 1.12.1
```

Confirm the active version:
```
julia --version
```

You should see `julia version 1.12.1`.

**NOTE**: If you need other versions of Julia for other purposes, you can run those other Julia versions using `julia +channel` (More info on the [juliaup README](https://github.com/JuliaLang/juliaup#using-juliaup)). Or you can easily switch between versions with juliaup. For example, to switch to version `1.11.2`, run `juliaup default 1.11.2`. To switch back to `1.12.1`, run `juliaup default 1.12.1`.

#### Step 3: Instantiate the Julia environment

Navigate to the ReEDS directory from the command line, then run:
```
julia --project=. instantiate.jl
```

#### Troubleshooting Issues with Julia Setup

`````{tab-set}
````{tab-item} Windows
When setting up Julia on Windows, you may run into some issues when running `julia --project=. instantiate.jl`. The following steps can be followed to help resolve issues and get Julia set up successfully:

1. If you've used another version of Julia (from the reeds2 conda environment or a previous installation), you may get errors about conflicting manifest. To get past this, you can delete the `Manifest.toml` file with `rm Manifest.toml` (on Unix systems) or `del Manifest.toml` (on Windows systems). 

2. Manually install [Random123](https://github.com/JuliaRandom/Random123.jl)

3. Re-run `julia --project=. instantiate.jl`

If that doesn't resolve the issue, try a clean install using juliaup:

1. Remove any previously installed Julia version managed by juliaup: `juliaup remove 1.12.1`

1. If Julia was installed outside of juliaup, uninstall it first: `winget uninstall julia`

1. Re-install Julia `1.12.1` via juliaup: `juliaup add 1.12.1 && juliaup default 1.12.1`

1. Open the Julia interactive command line: `julia`

1. Enter the Julia package manager by pressing `]`, then run the following commands:
    * `add Random123`
    * `registry add https://github.com/JuliaRegistries/General.git`
    * `instantiate`

1. Leave the package manager by pressing Backspace or Ctrl+C

1. Run the following commands to finish setup:
    * `import PRAS`
    * `import TimeZones`
    * `TimeZones.build()`

1. You can then leave the Julia command line by typing `exit()`
````

````{tab-item} macOS / Linux

If you experience issues, try the following:

1. Update to a known-good Julia version via juliaup:
    ```
    juliaup add 1.12.1
    juliaup default 1.12.1
    ```

2. Run `julia` from the terminal to open the interactive command line

3. Run:
    ```julia
    import Pkg
    Pkg.add("PRAS")
    Pkg.add("TimeZones")
    ```

4. Exit Julia with `exit()`, then re-run:
    ```
    julia --project=. instantiate.jl
    ```
````
`````

## Running ReEDS

**Quick Start:**
1. Navigate to the ReEDS directory from the command line
2. Activate environment: `conda activate reeds2`
3. Run the model: `python runreeds.py`
4. Follow the prompts for batch configuration
5. Check for a successful run: 
   1. Look for CSV files in `runs/[batchname_scenario]/outputs` (a successful run should have 100+ csv files in the outputs folder)
   2. Verify the reporting folders ("reeds-report", "reeds-report-reduced") exist in the outputs folder

### Understanding cases.csv
Switches are set in the cases.csv file and need to be specified by the user. The default case configuration is called "cases.csv".

General structure: 
- Column A: Model switches
- Column B: Switch descriptions
- Column C: Available choices (**note:** this is not available for all switches)
- Column D: Default values
- Column E: Your case configuration

**Note:** all monetary switches should be entered in 2004 dollars.

```{figure} figs/readme/cases-csv.png
:name: figure-cases-csv

Screenshot of cases.csv
```

**Additional cases_*.csv files:** 
- cases_standardscenarios.csv: contains all scenarios used for Standard Scenarios
- cases_test.csv: contains a group of "test" scenarios that are used to test various capabilities

The user may also create custom case configuration files by using the suffix in the file name (e.g., "cases_smalltests.csv"). It should follow the same column formatting as cases.csv, but does not need to include all available switches.

### Additional Resources
NLR has a YouTube channel that contains tutorial videos for ReEDS. The following are recommended videos for getting started with ReEDS: 
- Overview of ReEDS
  - [Introduction to the ReEDS Model (2026)](https://youtu.be/Qr56cj_2GQo?si=pu1v_hPHYRo8_fYH)
  - [Powered by ReEDS](https://www.youtube.com/watch?v=qLHdWh3uoHk)
- Getting started with ReEDS: [2023 ReEDS Training for User Group Meeting](https://www.youtube.com/watch?v=tDLwqH6YZ_E&amp;list=PLmIn8Hncs7bG558qNlmz2QbKhsv7QCKiC&amp;index=12)
- How to change inputs: [Training on Changing and Adding Inputs](https://www.youtube.com/watch?v=QxwEs0ZC5ns&amp;list=PLmIn8Hncs7bG558qNlmz2QbKhsv7QCKiC&amp;index=9)
- Debugging of ReEDS: [Training on Debugging ReEDS](https://www.youtube.com/watch?v=4I0V5F8fzDU&amp;list=PLmIn8Hncs7bG558qNlmz2QbKhsv7QCKiC&amp;index=8)

If you'd like practice with running a specific ReEDS scenario, you can walk through the [ReEDS Training Homework](reeds_training_homework).

Additional resources and learning:
* [General information on ReEDS](https://www.nlr.gov/analysis/reeds/)
* [GitHub README](https://github.com/ReEDS-Model/ReEDS/blob/main/README.md)
* [YouTube tutorials](https://www.youtube.com/playlist?list=PLmIn8Hncs7bG558qNlmz2QbKhsv7QCKiC)
* [GAMS language information](https://www.gams.com/latest/docs/UG_MAIN.html#UG_Language_Environment)

## Internal ReEDS Documentation
See the [NLR Specific ReEDS Documentation](https://nrel.sharepoint.com/:w:/s/ReEDS/Efathg8KjjtCkxW44vZpWQQBA2KsU3RadSsVauBMskEfUA?e=YaSIqc). Information on Yampa and HPC setup can be found there.
