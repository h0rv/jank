#!/usr/bin/env bash
# AI-assisted bounded native rendering check, after jank-build build.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LOG="$ROOT/artifacts/logs/flappy-bird-native-check.log"
set +e
docker exec --user "$(id -u):$(id -g)" jank-host-build \
  xvfb-run -a timeout 3s "$ROOT/artifacts/app/flappy-bird/native/flappy-bird" > "$LOG" 2>&1
STATUS=$?
set -e
cat "$LOG"
[[ $STATUS == 124 ]] || { echo "FLAPPY BIRD NATIVE: FAIL unexpected exit $STATUS" >&2; exit 1; }
rg -Fq 'Default shader loaded successfully' "$LOG"
rg -Fq 'FONT: Default font loaded successfully' "$LOG"
echo 'FLAPPY BIRD NATIVE: PASS'
