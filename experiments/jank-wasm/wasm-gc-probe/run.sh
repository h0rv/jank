#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
SDK=${EMSDK:-/home/ubuntu/tools/emsdk}
CC="$SDK/upstream/bin/clang"
BIN="$SDK/upstream/bin"
OUT=../artifacts/wasm-gc-probe
mkdir -p "$OUT"
"$BIN/wasm-as" gc.wat --enable-gc --enable-reference-types -o "$OUT/gc.wasm"
"$CC" --target=wasm32 -mreference-types -nostdlib -Wl,--no-entry -Wl,--export-all refs.cpp -o "$OUT/refs.wasm"
"$CC" --target=wasm32 -mreference-types -nostdlib -Wl,--no-entry -Wl,--export-all hybrid.c -o "$OUT/hybrid.wasm"
for test in BAD_FIELD BAD_HEAP BAD_ARRAY BAD_ADDRESS; do
  echo "=== expected rejection: $test ==="
  if "$CC" --target=wasm32 -mreference-types -D"$test" -fsyntax-only refs.cpp; then
    echo "ERROR: unexpectedly accepted $test"; exit 1
  fi
done
echo '=== funcref syntax ==='
"$CC" --target=wasm32 -mreference-types -DFUNCREF -fsyntax-only refs.cpp
node run.mjs "$OUT"
