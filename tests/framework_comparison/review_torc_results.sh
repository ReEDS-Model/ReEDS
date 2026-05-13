#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${1:-tests/framework_comparison/torc_output/torc.db}"
RESULT_DIR="$(dirname "$DB_PATH")/framework_results"

if [[ ! -f "$DB_PATH" ]]; then
  echo "ERROR: Torc DB not found: $DB_PATH" >&2
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "ERROR: sqlite3 not found on PATH" >&2
  exit 1
fi

echo "Torc DB: $DB_PATH"
echo

echo "== Torc runtime and memory =="
sqlite3 -header -column "$DB_PATH" \
  "select j.name,
          round(r.exec_time_minutes * 60, 3) as torc_s,
          round(r.peak_memory_bytes / 1024.0 / 1024.0, 1) as peak_mb,
          r.return_code
   from job j
   join result r on r.job_id = j.id
   order by j.id;"

echo

echo "== Framework adapter results =="
if [[ ! -d "$RESULT_DIR" ]]; then
  echo "No framework result directory found: $RESULT_DIR"
  exit 0
fi

sqlite3 -noheader "$DB_PATH" "select name from job order by id;" \
  | sed -E 's/^bench_(.*)_(small|medium|large|xlarge)$/\2_\1.json/' \
  | while IFS= read -r name; do
  result="$RESULT_DIR/$name"
  [[ -e "$result" ]] || continue
  python - "$result" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
framework = data.get("label") or data.get("framework", "?")
size = data.get("size", "?")
error = data.get("error")
if error:
    first_line = str(error).splitlines()[0]
    print(f"{framework:16s} {size:8s} ERROR  {first_line}")
else:
    objective = data.get("objective")
    build_s = data.get("build_s")
    solve_s = data.get("solve_s")
    total_s = data.get("total_s")
    print(
        f"{framework:16s} {size:8s} OK     "
        f"build={build_s:.3f}s solve={solve_s:.3f}s total={total_s:.3f}s "
        f"obj={objective:,.0f}"
    )
PY
done
