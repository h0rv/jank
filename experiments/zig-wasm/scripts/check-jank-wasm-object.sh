#!/usr/bin/env bash
# Compile the actual generated jank module, not the full target runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
JANK="${JANK:-jank}"
RUNTIME="${JANK_RUNTIME_DIR:-/opt/homebrew/opt/jank/lib/jank/0.1}"
EMXX="${EMXX:-$ROOT/.tools/gc-wasm/emsdk/upstream/emscripten/em++}"
VERSION="$("$JANK" print-binary-version)"
SOURCE="jank/target/_cache/$VERSION/spike/core.cpp"
if [[ ! -f "$SOURCE" ]]; then
  echo 'Generate the C++ source first: bash scripts/check-jank-zig-cpp.sh' >&2
  exit 2
fi
if [[ ! -x "$EMXX" ]]; then
  echo 'Set EMXX or bootstrap the local SDK using scripts/check-gc-wasm.sh' >&2
  exit 2
fi
mkdir -p artifacts/wasm-probe
"$EMXX" -m64 -fwasm-exceptions -std=c++20 -O2 \
  -DBOOST_MP_STANDALONE=1 -DIMMER_HAS_LIBGC=1 -DIMMER_TAGGED_NODE=0 \
  -DPOINTER_MASK=0x0000FFFFFFFFFFFF -I "$RUNTIME/include" \
  -c "$SOURCE" -o artifacts/wasm-probe/jank-module64.o \
  >artifacts/wasm-probe/jank-module64-emscripten.log 2>&1
file artifacts/wasm-probe/jank-module64.o
echo 'Actual jank-generated module compiled to wasm64 object; not linked or executed'
