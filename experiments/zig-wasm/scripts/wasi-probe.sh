#!/usr/bin/env bash
# AI-assisted bounded Emscripten memory64 -> Wasmtime Preview 1 experiment.
set -euo pipefail
source "$(dirname "$0")/wasi-tools.sh"
cd "$ROOT"
wasi_tools
run() {
  local name=$1 rc=0; shift
  { printf '$ '; printf '%q ' "$@"; printf '\n'; "$@" || rc=$?; printf 'EXIT=%s\n' "$rc"; } > "$L/step3-$name.log" 2>&1
  tail -n 16 "$L/step3-$name.log"
  return "$rc"
}
run prerequisites python3 -B "$ROOT/scripts/wasi-bootstrap.py"
run standalone-link bash "$ROOT/scripts/wasi-standalone-link.sh"
run spill docker exec --user "$(id -u):$(id -g)" jank-host-build artifacts/build-binaryen/bin/wasm-opt \
  "$P/spike-standalone.wasm" "${features[@]}" --flatten --spill-pointers -g -o "$P/spike-standalone-spill.wasm"
run imports "$NODE" "$ROOT/scripts/wasi-imports.mjs" "$P/spike-standalone-spill.wasm" "$P/spike-standalone-renamed.wasm"
run shim-compile-link wasi_compile_shim
run merge "$B/wasm-merge" "$P/spike-standalone-renamed.wasm" main \
  "$P/wasi64-shim.wasm" shim_snapshot_preview1 "${features[@]}" -g -o "$P/spike-wasi-merged.wasm"
run exnref "$B/wasm-opt" "$P/spike-wasi-merged.wasm" "${features[@]}" --translate-to-exnref -g -o "$P/spike-wasi.wasm"
run inspect "$B/wasm-dis" "$P/spike-wasi.wasm" -o "$P/spike-wasi.wat"
rg '^ \(import|^ \(memory|^ \(export "memory"' "$P/spike-wasi.wat" > "$L/step3-final-imports.log"
if rg '^ \(import "(env|main|shim_snapshot_preview1)"' "$P/spike-wasi.wat"; then
  echo 'Unresolved bridge import' >&2
  exit 1
fi
run wasmtime "$W" run -W memory64=y -W exceptions=y "$P/spike-wasi.wasm" static-roots
grep -Fxq 'jank -> Zig: scalar and wide result checks passed' "$L/step3-wasmtime.log"
grep -Fxq 'jank -> Zig: borrowed-buffer checks passed' "$L/step3-wasmtime.log"
echo 'WASI SPIKE VERDICT: PASS (both markers and exit 0)'
