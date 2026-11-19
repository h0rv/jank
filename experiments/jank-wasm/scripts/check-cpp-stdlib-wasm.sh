#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ZIG="${ZIG:-zig}"
mkdir -p artifacts/wasm-probe
"$ZIG" c++ -target wasm32-wasi -mexec-model=reactor -std=c++20 -O2 \
  -fno-exceptions -fno-rtti -Wl,--export=cpp_vector_sum \
  wasm-probe/stdlib.cpp -o artifacts/wasm-probe/stdlib32.wasm
node wasm-probe/stdlib.mjs

if "$ZIG" c++ -target wasm64-wasi -mexec-model=reactor -std=c++20 -O2 \
  -fno-exceptions -fno-rtti -Wl,--export=cpp_vector_sum \
  wasm-probe/stdlib.cpp -o artifacts/wasm-probe/stdlib64.wasm \
  >artifacts/wasm-probe/stdlib64.log 2>&1; then
  echo 'wasm64 C++ standard library now builds; add an execution test before relying on it'
else
  grep -F 'unable to provide libc' artifacts/wasm-probe/stdlib64.log
  echo 'Zig wasm64-wasi libc is unavailable in this toolchain; see the log'
fi
