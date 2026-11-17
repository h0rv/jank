#!/usr/bin/env bash
# AI-assisted bounded native rendering and shared-rule check, after jank-build build.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
LOG="$ROOT/artifacts/logs/pacman-native-check.log"
docker exec --user "$(id -u):$(id -g)" jank-host-build \
  xvfb-run -a "$ROOT/artifacts/app/pacman/native/pacman" 2 > "$LOG" 2>&1
cat "$LOG"
for marker in 'pacman: rules passed' 'pacman: initialized' 'pacman: native loop completed'; do
  if ! rg -qx "$marker" "$LOG"; then
    echo "PACMAN NATIVE: FAIL missing $marker" >&2
    exit 1
  fi
done
echo 'PACMAN NATIVE: PASS'
