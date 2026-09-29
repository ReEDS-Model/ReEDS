#!/bin/bash
# Runs cmm_custom_report.gms for every base_* run (2041 checkpoint),
# then merges GDX outputs and dumps two parameters to CSV.
#
# Parallelism: set NJOBS to the number of concurrent GAMS processes allowed
# by your license (default 32; node has 104 cores).

REEDS=/projects/finitoreeds/kpitman/ReEDS
RUNS=${REEDS}/runs
OUTPUT=${RUNS}/cmm_custom_2026
NJOBS=4

mkdir -p "$OUTPUT"

# -- worker function (called once per run by xargs) ----------------------
run_case() {
    local rundir="$1"
    local runname case g00
    runname=$(basename "$rundir")
    case="${runname#base_}"
    g00="${rundir}/g00files/${runname}_2041i0.g00"

    if [[ ! -f "$g00" ]]; then
        echo "WARNING: $g00 not found, skipping $case" >&2
        return 1
    fi

    cd "$REEDS" && gams cmm_custom_report.gms \
        r="$g00" \
        --case="$case" \
        --outdir="$OUTPUT" \
        lo=0 \
        o="${OUTPUT}/lst_${case}.lst" \
        lf="${OUTPUT}/log_${case}.log" \
    && echo "Done: $case" \
    || echo "FAILED: $case" >&2
}
export -f run_case
export REEDS OUTPUT

# -- run all base_* cases in parallel ------------------------------------
echo "Running cmm_custom_report.gms for all base_* runs (NJOBS=${NJOBS})..."
find "$RUNS" -mindepth 1 -maxdepth 1 -type d -name 'base_*' | sort |
    xargs -P "$NJOBS" -I{} bash -c 'run_case "$@"' _ {}

# -- merge and dump ------------------------------------------------------
echo "Merging GDX files..."
gdxmerge o="${OUTPUT}/merged_materials.gdx" "${OUTPUT}"/cmm_report_*.gdx

echo "Dumping material_demand to CSV..."
gdxdump "${OUTPUT}/merged_materials.gdx" \
    output="${OUTPUT}/material_demand.csv" \
    symb=material_demand \
    format=csv \
    header="scen,tcat,material,state,year,value"

echo "Dumping rep_mat to CSV..."
gdxdump "${OUTPUT}/merged_materials.gdx" \
    output="${OUTPUT}/rep_mat.csv" \
    symb=rep_mat \
    format=csv \
    header="scen,material,year,parameter,value"

echo "All done."