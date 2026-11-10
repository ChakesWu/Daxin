#!/usr/bin/env bash
# Run the whole range once: three server configurations x the generated questions. SIMULATED; local only.
# Usage: testkit/range/run_all.sh WORKDIR   (needs DAXIN_HTTP_ENABLED=1; the model key comes from the environment or a proxy)
set -euo pipefail
W="${1:?workdir}"; R="$(cd "$(dirname "$0")" && pwd)"; export DAXIN_HTTP_ENABLED=1
mkdir -p "$W"; python "$R/setup_workspace.py" "$W/ws"
declare -A RUNS=( [A1]=default [B2]=scoped [C3]=stale ); PORT=8801
for run in A1 B2 C3; do
  python "$R/server.py" --preset "${RUNS[$run]}" --port $PORT > "$W/server_$run.log" 2>&1 & PID=$!
  until grep -q "range up" "$W/server_$run.log" 2>/dev/null; do sleep 2; done
  daxin ask "$W/ws/questions.json" "http://127.0.0.1:$PORT/" --run "$run" --ws "$W/ws" --meta-out "$W/meta_$run.json" --interval 1
  kill $PID; PORT=$((PORT+1))
done
daxin judge --ws "$W/ws"
