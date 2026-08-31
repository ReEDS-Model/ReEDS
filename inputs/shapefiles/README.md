## Shapefiles Input Files

- `ctus_cs_polygons.gpkg`: Polygons of the CO<sub>2</sub> storage formations (geologic sinks) used for carbon transport and storage
  - The `cs` attribute names each formation and corresponds to `inputs/ctus/cs.csv`
  - Also carries formation deposition, depth [ft], thickness [ft], basin, lithology, centroid state, and CO<sub>2</sub> storage capacity [MMT CO<sub>2</sub>]

- `greatlakes.gpkg`: Great Lakes polygons, used for cartographic masking in mapping and plotting scripts

- `h2_storage_sites.gpkg`: Polygons of candidate geologic hydrogen storage sites
  - Contains a separate layer for each storage type (`salt` and `hardrock`)

- `offshore_zones.gpkg`: Polygons of the offshore wind zones

- `state_fips_codes.csv`: Mapping of states to FIPS codes and postal code abbreviations

- `timezones.gpkg`: Time zone polygons, used to assign a time zone to each ReEDS region
