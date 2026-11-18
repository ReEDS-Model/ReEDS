## Top-Level Input Files

- `remote_files.csv`: Registry of input files that are hosted remotely because of their size
  - Columns give the file name (`filename`), the `inputs/profiles_*` folder it is linked into (`inputs_path`), the URL template (`url_base`), the remote record ID (`record_id`), and the file's MD5 checksum (`md5`)
  - Read by `reeds/remote.py`, which downloads the files a run needs to `inputs/remote/`, adds the `record_id` to each saved file name, and links the current version into the `inputs_path` folder under its original name

- `scalars.csv`: Scalar parameters used throughout the model
  - Columns are the scalar name, its value, and a description, with units between `--` markers in the description
  - Read in Python by `reeds.io.get_scalars()` and converted to `inputs_case/scalars.txt` for GAMS
  - Each `years_until_*` scalar also produces a `firstyear_*` scalar, equal to its value plus `this_year`

- `tech-subset-table.csv`: Lookup table assigning technologies (rows) to technology groups (columns), where `YES` marks membership
  - Read into GAMS as `i_subsets(i,i_subtech)`
  - Row labels can use GAMS range notation (e.g., `evmc_storage_1*evmc_storage_10`)
