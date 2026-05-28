import pandas as pd

esm_all = [ 
        #    "ecearth3cc", 
            "ecearth3cc2000", 
            # "ecearth3cc2010", 
        #    "ecearth3veg", 
            # "gfdlcm4",
        #    "mpiesm12hr", 
        #   "taiesm1"
            ]

for esm in esm_all:
    resource = "upv"
    class_bin_col = "sc_gid"
    class_raw = pd.read_csv(f"/projects/alcaps/jcarag/ReEDS-2.0/hourlize/out/{resource}_{esm}_ba/results/{resource}_supply_curve_raw.csv")
    class_raw = class_raw[["class",class_bin_col]].sort_values(class_bin_col)
    # class_raw = class_raw.drop_duplicates("class")
    class_raw.to_csv(f"inputs/resource/{resource}_{esm}_classes.csv",index=False)

    resource = "wind-ons"
    class_bin_col = "sc_gid"
    class_raw = pd.read_csv(f"/projects/alcaps/jcarag/ReEDS-2.0/hourlize/out/{resource}_{esm}_ba/results/{resource}_supply_curve_raw.csv")
    class_raw = class_raw[["class",class_bin_col]].sort_values(class_bin_col)
    # class_raw = class_raw.drop_duplicates("class")
    class_raw.to_csv(f"inputs/resource/{resource}_{esm}_classes.csv",index=False)
