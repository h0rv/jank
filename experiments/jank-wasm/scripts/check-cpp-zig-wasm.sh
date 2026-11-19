#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ZIG="${ZIG:-zig}"
mkdir -p artifacts/wasm-probe
for bits in 32 64; do
  "$ZIG" build-obj native.zig -target "wasm${bits}-freestanding" \
    -O ReleaseSafe -femit-bin="artifacts/wasm-probe/zig-${bits}.o"
  "$ZIG" c++ -target "wasm${bits}-freestanding" -std=c++20 -O2 \
    -nostdlib -Wl,--no-entry -Wl,--export=cpp_calls_zig \
    wasm-probe/minimal.cpp "artifacts/wasm-probe/zig-${bits}.o" \
    -o "artifacts/wasm-probe/cpp-zig-${bits}.wasm"
done
node wasm-probe/cpp-zig.mjs
