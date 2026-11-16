#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
ZIG="${ZIG:-zig}"
JANK="${JANK:-jank}"

"$ZIG" build -Doptimize=ReleaseSafe
"$ZIG" build test
(
  cd jank
  "$JANK" --module-path src -L "$ROOT/zig-out/lib" -l:spike run-main spike.core
  "$JANK" --module-path src -L "$ROOT/zig-out/lib" -l:spike compile spike.core --name jank-spike
)
(cd /tmp && "$ROOT/jank/target/jank-spike")
