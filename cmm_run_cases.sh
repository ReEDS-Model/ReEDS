#!/bin/bash
# Runs cmm_custom_report.gms for every run folder listed in
# postprocessing/bokehpivot/reeds_scenarios_buildout.csv,
# then merges GDX outputs and dumps two parameters to CSV.
#
# Parallelism: set NJOBS to the number of concurrent GAMS processes allowed
# by your license (default 4).

set -euo pipefail

REEDS=${REEDS:-/projects/finitoreeds/kpitman/ReEDS}
RUNS=${RUNS:-${REEDS}/runs}
CSV=${CSV:-${REEDS}/postprocessing/bokehpivot/reeds_scenarios_buildout_testing.csv}
OUTPUT=${OUTPUT:-${RUNS}/cmm_custom_2026_buildout_testing}
NJOBS=${NJOBS:-4}

mkdir -p "$OUTPUT"

if [[ ! -f "$CSV" ]]; then
    echo "ERROR: scenario CSV not found: $CSV" >&2
    exit 1
fi

# Resolve the 1-based index of the 'path' column in the CSV header.
path_col=$(awk -F',' '
NR == 1 {
    for (i = 1; i <= NF; i++) {
        if ($i == "path") {
            print i
            exit
        }
    }
}
' "$CSV")

if [[ -z "${path_col:-}" ]]; then
    echo "ERROR: CSV header does not contain a 'path' column: $CSV" >&2
    exit 1
fi

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

# Build a unique run folder list from the CSV path column.
RUNLIST=$(mktemp)
awk -F',' -v col="$path_col" 'NR > 1 && $col != "" { print $col }' "$CSV" | sort -u > "$RUNLIST"

count=$(wc -l < "$RUNLIST")
if [[ "$count" -eq 0 ]]; then
    echo "ERROR: no run folders found in $CSV" >&2
    rm -f "$RUNLIST"
    exit 1
fi

# -- run all listed cases in parallel ------------------------------------
echo "Running cmm_custom_report.gms for $count CSV-listed runs (NJOBS=${NJOBS})..."
xargs -P "$NJOBS" -I{} bash -c 'run_case "$@"' _ {} < "$RUNLIST"

rm -f "$RUNLIST"

# -- merge and dump ------------------------------------------------------
echo "Merging GDX files..."
shopt -s nullglob
GDX_FILES=("${OUTPUT}"/outputs_*.gdx)
if (( ${#GDX_FILES[@]} == 0 )); then
    echo "ERROR: no per-case outputs_*.gdx files found in $OUTPUT" >&2
    exit 1
fi
gdxmerge o="${OUTPUT}/merged_materials.gdx" "${GDX_FILES[@]}"

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
