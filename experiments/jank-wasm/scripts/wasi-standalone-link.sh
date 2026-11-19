#!/usr/bin/env bash
# AI-assisted standalone link of the repository startup-spill objects.
set -euo pipefail
source "$(dirname "$0")/wasi-tools.sh"
cd "$ROOT"
export TMPDIR="$ROOT/artifacts/tmp"
export EM_CONFIG="$ROOT/.tools/gc-wasm/emsdk/.emscripten"
E="$ROOT/.tools/gc-wasm/emsdk/upstream/emscripten/em++"
O="$ROOT/artifacts/wasm64-spike"
mkdir -p "$P" "$TMPDIR"
set -x
"$E" -x c -sMEMORY64=1 -fwasm-exceptions -O2 -g -c "$SOURCES/wasi-shim-scratch.c" -o "$P/wasi-shim-scratch.o"
"$E" -O2 -g --profiling-funcs -sMEMORY64=1 -fwasm-exceptions \
  -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=4194304 -sSTANDALONE_WASM -sERROR_ON_UNDEFINED_SYMBOLS=1 \
  "$O/startup-spill-main.o" "$O/startup-spill-core.o" "$O/startup-spill-driver.o" \
  "$O/startup-spill-zig.o" "$P/wasi-shim-scratch.o" \
  artifacts/build-wasm64/libjank-static-runtime.a \
  -Wl,--export=wasi_shim_scratch -Wl,--error-limit=0 -o "$P/spike-standalone.wasm"
