## Ctus Input Files

- `co2_site_char.csv`: Characteristics of each CO<sub>2</sub> storage site: maximum injection rate [metric tons/hour], maximum storage capacity [Mton], and break-even storage cost [$/metric ton] at a range of capacity factors
  - Break-even cost columns are named `bec_{CF}`; the column used is selected by the `GSw_CO2_BEC` switch
  - Costs are in the dollar year given by `dollaryear.csv` and are deflated during input processing

- `cs.csv`: List of CO<sub>2</sub> storage sites (geologic formations) recognized by the model
  - A superset of the sites in `co2_site_char.csv`; only sites with characteristics are available for storage

- `dollaryear.csv`: U.S. dollar year for each cost-related input file in this folder
