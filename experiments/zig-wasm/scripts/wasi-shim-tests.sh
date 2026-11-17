#!/usr/bin/env bash
# AI-assisted normal, empty, error and bounds checks of the actual ABI adapter.
set -euo pipefail
source "$(dirname "$0")/wasi-tools.sh"
wasi_tools
wasi_compile_shim
"$B/wasm-as" "$SOURCES/wasi-shim-tests.wat" --enable-memory64 -o "$P/wasi-shim-tests.wasm"
"$B/wasm-merge" "$P/wasi-shim-tests.wasm" main "$P/wasi64-shim.wasm" shim_snapshot_preview1 \
  --enable-memory64 --enable-mutable-globals -o "$P/wasi-shim-tests-merged.wasm"
for test in normal empty bad_fd arguments; do
  "$W" run -W memory64=y --invoke "$test" "$P/wasi-shim-tests-merged.wasm" alpha beta
  echo "SHIM TEST: $test PASS"
done
for test in high_pointer crossing_buffer excess_iovecs; do
  rc=0
  "$W" run -W memory64=y --invoke "$test" "$P/wasi-shim-tests-merged.wasm" > "$L/test-$test.log" 2>&1 || rc=$?
  test "$rc" -ne 0
  grep -Fq 'wasm trap: wasm `unreachable` instruction executed' "$L/test-$test.log"
  echo "SHIM TEST: $test PASS (expected trap, exit=$rc)"
done
echo 'SHIM TEST VERDICT: PASS'
