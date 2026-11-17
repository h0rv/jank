#!/usr/bin/env bash
# AI-assisted bounded native rendering check, after jank-build build.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LOG="$ROOT/artifacts/logs/flappy-bird-native-check.log"
docker exec --user "$(id -u):$(id -g)" jank-host-build \
  xvfb-run -a "$ROOT/artifacts/app/flappy-bird/native/flappy-bird" smoke > "$LOG" 2>&1
cat "$LOG"
for marker in 'flappy-bird: rules passed' 'flappy-bird: initialized' 'flappy-bird: native loop completed'; do
  rg -qx "$marker" "$LOG" || { echo "FLAPPY BIRD NATIVE: FAIL missing $marker" >&2; exit 1; }
done
echo 'FLAPPY BIRD NATIVE: PASS'
