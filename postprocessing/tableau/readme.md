# Publication of ReEDS Study Results in Tableau

This folder contains files that facilitate the postprocessing and publication of ReEDS study results via [Tableau Public](https://public.tableau.com/app/discover), a free online platform used to create and share visualizations. This functionality is designed for final publication of ReEDS results, however it may be useful for comparing suites of runs during project iteration as well. This data processing and visualization publication process is designed for researchers without prior experience using Tableau; however previous Tableau experience is advantageous.

#### Process Overview (discussed in detail in the subsequent sections)
1. Request a Tableau license through the IT Service portal, download Tableau Desktop and activate your license.
2. Run `tableau_viz_suite.py` to synthesize your run results into csvs.
3. Load your csvs into the template Tableau workbooks, `ReEDS_Study_Results_Charts.twbx` and `ReEDS_Study_Results_Maps.twbx`.
4. Customize the Tableau workbooks for your study.
5. Publish Tableau workbook and accompanying data (if desired).

## Detailed instructions of how to publish your study's results with Tableau Public

### Step 1: Set up Tableau
1. [Tableau](https://www.tableau.com/) is a commercial software that requires a license. Licenses are available through NLR overhead funds for no additional cost to projects. Request a license through the [Tableau catalog item](https://nrel.servicenowservices.com/sp?id=sc_cat_item_guide&sys_id=9c54d9cc874b7910496140070cbb35d7) in the IT Service portal. Under 'Product/Version', select 'Tableau Creator'. This includes Tableau Desktop and will allow you to edit Tableau workbooks, as opposed to purely viewing them. 
2. Install [Tableau Desktop](https://www.tableau.com/products/desktop/download) on your local machine. IT will complete this with you with your license ticket, as submitted in Step 1.   
3. Activate your license. IT will most likely complete this with you with your license ticket, as submitted in Step 1. If they do not, Tableau Desktop installations activate by authenticating to [Tableau Server](https://tableau.nlr.gov/). All licensed Tableau users have been added to the Server. The Server will activate Desktop installations for users assigned a Tableau Creator license. Note: Computers must be connected to NLR's enterprise network (onsite or by VPN) to authenticate to Tableau Server. To activate an existing installation of Tableau:
    - Open Tableau and go to Help > Manage Product Keys.  
    - Click the Activate button and select Activate by signing into a server.  
    - In the Server field, enter https://tableau.nlr.gov
    - Click Connect

** If you are no longer using your Tableau license please let the ITS Asset Management team know so that the license seat can be used by someone else. 

### Step 2: Run tableau_viz_suite.py

1. Confirm your inputs: 
- Scenario name and filepaths, as shown in `ReEDS\postprocessing\example.csv`. `tableau_viz_suite.py` will point to this csv to know which scenarios to include.
    - Note: the "casename" column in `ReEDS\postprocessing\example.csv` will become the name shown in the CSV files that you may ultimately publish. It is recommended to choose decipherable scenario names for a general audience not familiar with your scenario matrix. For example, instead of "Scenario1" you may call it "MidDemand_RefTransmission_DefaultPolicy". Each value in the "casename" column must be unique.
- Description of your suite of scenarios, to be used in the Tableau workbook: `ReEDS\postprocessing\tableau\scenarios.csv`. This should correspond to the scenarios used in `ReEDS\postprocessing\example.csv` in the "casename" column. If you do not populate `ReEDS\postprocessing\tableau\scenarios.csv`, the script will attempt to automatically assign metadata of your scenarios based on the cases.csv switches they used. This is imperfect for publication ready datasets but works well for quick analyses and interrim results. If the script cannot populate `ReEDS\postprocessing\tableau\scenarios.csv` automatically, the script will break.
    - Note: Each value in the "Scenario Name" column must be unique. This is what is visible in the Tableau workbooks.
- Technology mapping and cost mapping are pulled from the bokehpivot csvs (see `ReEDS\postprocessing\bokehpivot\in\reeds2`). To change those settings, alter the mappings in the bokehpivot csvs.
- No additional packages are needed beyond the default ReEDS environment.
2. Run tableau_viz_suite.py 

##### Example calls:

```
python postprocessing/tableau/tableau_viz_suite.py ../example.csv                                          # run tableau_viz_suite.py with scenarios in example.csv
python postprocessing/tableau/tableau_viz_suite.py ../example.csv  --region_filter interconnect/eastern    # run tableau_viz_suite.py with only Eastern interconnect results
python postprocessing/tableau/tableau_viz_suite.py ../example.csv --years [2025,2035,2050]                 # run tableau_viz_suite.py with a select set of model years

*Note: this process is effective on Kestrel login or compute nodes or locally. 
However, it has has not been configured to submit jobs on Kestrel because even with suites of 100+ runs, it only takes a couple minutes to process. 
```

3. Expected outputs: expected output is a directory of csvs and shapefiles `ReEDS\postprocessing\tableau\out\report-{datetime}`.


### Step 3: Load your data into template Tableau workbook
1. Open the `ReEDS_Study_Results_Charts.twbx` file in Tableau Desktop. You will do the same process for `ReEDS_Study_Results_Maps.twbx` afterwards.
2. If you have not yet authenticated your Tableau license, you may be directed to confirm that. Please see the 3rd bullet point under `Step 1: Set up Tableau`.
3. You may also be asked to "Allow Extension" in a pop-up box. Click "OK". That extension is needed for the workbook to function properly.
4. On the bottom left hand corner, click on "Data Source". 
Under "Connections", in the top-left hand corner, click on the down arrow next to "Scenarios". Click "Edit Connection". 
Change the directory to the location of the csv files you produced with `tableau_viz_suite.py`. Default location is `ReEDS\postprocessing\tableau\out\report-{datetime}`. Do this for each of the "Connections" in the workbook. For the `ReEDS_Study_Results_Charts.twbx` workbook, this is "Scenarios", "CSV Files" and "Hierarchy".  For the `ReEDS_Study_Results_Maps.twbx` workbook, this is "Scenarios", "CSV Files", "Transmission Endpoints", "US_PCA" and "Hierarchy".
- Note: When altering the path for the `hierarchy.csv` file, point the path to the Tableau script outputs (ex. postprocessing/tableau/out/report-*), not `inputs/hierarchy.csv`.
5. Clicking into this folder will automatically update the data. You should now see the new data populated throughout the notebook if you click to the other tabs, which are referred to as "Dashboards" in Tableau.
6. If you do not see your data populating the "Dashboards", there are a couple common culprits.
- Under "Data Source", check for any red exclamation marks. This may indicate a missing csv or improper join.
- If you have a large dataset, the data may take a few minutes to load.
- The "Dashboards" are set to view all scenarios by default, i.e. not filtering out any scenarios. However, that setting can get changed if you are editing the workbook so go into one of the Sheets and confirm that "Scenario Name" and "Sensitivity" are set to "Use all".


### Step 4: Customize Tableau workbooks to your project's needs

- Tableau is endlessly customizable so this README does not attempt to go through how to customize your workbook. Tableau's online resources are generally quite good if you search the internet for "how do I do X in Tableau?". See more infomation in the "Further Tableau Learning" section.
- If you are an NLR ReEDS user looking for additional support customizing your visualizations, please reach out to Anne Hamilton.

### Step 5: Publish Tableau workbook and accompanying data (if desired)

- Assuming you have `ReEDS_Study_Results_Charts.twbx` and `ReEDS_Study_Results_Maps.twbx` configured to your liking, with your custom data, and you have saved your workbook locally, you are ready to publish. 
- Create an [Tableau Public](https://public.tableau.com/app/discover) account. It is recommended that the name of your account is the name of your study as it will appear next to your published workbooks. For example, you might name your account "Standard Scenarios", instead of "First Name Last Name" of the researcher. 
- Update your profile photo to something representative of your study.
- Click on your profile photo in the top right hand corner and click "My Profile". By default, this will bring you to the "Vizzes" tab. To create a new visualization, click "Create a Viz". It will prompt you to add a file. Click "Upload from computer" and direct it to your `ReEDS_Study_Results_Charts.twbx`. You will do `ReEDS_Study_Results_Maps.twbx` next in the same way.
- When you are ready to publish, open your Tableau workbok and click on "Server" in the top banner. Then click "Tableau Public", then "Save to Tableau Public As". Sign in with your email and password. A pop-up will warn you that you are about to publish a workbook publically. Change the title of your workbook here, if desired, and then click "Save". Tableau Public will automatically open in your default web browser. To see your new visualization, click on your profile photo in the top right hand corner and click "My Profile". Under "Vizzes" you will now see your new workbook.
    - Note: It is highly recommended to make your visualization hidden until you are ready for it to be shared externally. To do so, click on the three dots next to your visualization and turn off "Show Viz on Profile" and "Feature Viz on Profile" (blue toggle = on, grey toggle = off). Now the visualizations are shown under "Hidden". No one will be able to see your visualization unless you share the URL with them.
- Embed your Tableau workbook in your study webpage (if desired). Coordinate with your Communications representative for this. Example shown on the [National Transmission Planning webpage](https://www.nlr.gov/grid/national-transmission-planning-study).
- For study transparency and ease of use, it is recommended to publish the underlying csv files. One way to do this is via the [Open Energy Data Initiative (OEDI)](https://data.openei.org/), which is a "a centralized repository of datasets aggregated from the U.S. Department of Energy’s Programs, Offices, and National Laboratories". You can submit a new dataset [here](https://data.openei.org/submit).

## Troubleshooting

`tableau_viz_suite.py` relies on the `ReEDS/reeds` functions and functions in bokehpivot. Errors may be derived from broken functionality there.  

## Known Incompatibilities
- Mixed resolution scenarios - this postprocessing pipeline is currently only configured
- ReEDS-India - since this postprocessing pipeline pulls from specific ReEDS output and inputs_case files, it is currently not compatible with ReEDS-India. 

## Further Tableau Learning
If you are interested in learning more about Tableau or hit issues, below are some additional resources:
- [Tableau Help Page](https://www.tableau.com/support/help) - helpful documentation of layouts, features and functionality
- [Tableau Community Forums](https://community.tableau.com/s/explore-forums) - helpful for specific "how do I do ___?" type questions
