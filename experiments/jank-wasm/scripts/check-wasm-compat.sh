#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ZIG="${ZIG:-zig}"
TOOLS="$PWD/.tools/wasm-probe"
LOGS="$PWD/artifacts/wasm-probe"
mkdir -p "$TOOLS" "$LOGS"

curl -fsSL 'https://raw.githubusercontent.com/jank-lang/jank/43ffa8d0a6bce1c17c552c6d46f4d6486dc304ed/compiler%2Bruntime/include/cpp/jtl/primitive.hpp' -o "$TOOLS/primitive.hpp"
curl -fsSL 'https://raw.githubusercontent.com/jank-lang/bdwgc/327ef1f8c80a611b2f8b915850c8b2fd38e6595e/include/private/gcconfig.h' -o "$TOOLS/gcconfig.h"

expect_rejection() {
  local name="$1" expected="$2"
  shift 2
  if "$@" >"$LOGS/$name.log" 2>&1; then
    echo "Unexpected success: $name" >&2
    exit 1
  fi
  if ! grep -Fq "$expected" "$LOGS/$name.log"; then
    echo "Unexpected failure reason: $name; see $LOGS/$name.log" >&2
    exit 1
  fi
  echo "Confirmed rejection: $name ($expected)"
}

"$ZIG" c++ -std=c++20 -c -I "$TOOLS" wasm-probe/primitive.cpp -o "$LOGS/native-primitive.o"
expect_rejection jank-wasm32 'static assertion failed' \
  "$ZIG" c++ -target wasm32-freestanding -std=c++20 -c \
  -I "$TOOLS" wasm-probe/primitive.cpp -o "$LOGS/wasm32-primitive.o"
expect_rejection jank-wasm64-platform 'Unsupported environment.' \
  "$ZIG" c++ -target wasm64-freestanding -std=c++20 -c \
  -I "$TOOLS" wasm-probe/primitive.cpp -o "$LOGS/wasm64-primitive.o"

# A synthetic Unix macro isolates the pointer checks. It is NOT a platform port.
"$ZIG" c++ -target wasm64-freestanding -D__unix__ -std=c++20 \
  -c -I "$TOOLS" wasm-probe/primitive.cpp -o "$LOGS/wasm64-primitive-isolated.o"
echo 'wasm64 passes the primitive pointer checks with the platform guard bypassed'

expect_rejection gc-wasm64 '64-bit WebAssembly is not yet supported' \
  "$ZIG" cc -target wasm64-freestanding -D__wasi__ -E \
  -I "$TOOLS" wasm-probe/collector.c
expect_rejection gc-wasm32-threads 'No multi-threading support yet' \
  "$ZIG" cc -target wasm32-wasi -DGC_THREADS -E \
  -I "$TOOLS" wasm-probe/collector.c

"$ZIG" build-exe native.zig -target wasm32-freestanding -fno-entry \
  -rdynamic -O ReleaseSafe -femit-bin=artifacts/spike.wasm
node wasm-probe/zig-baseline.mjs
