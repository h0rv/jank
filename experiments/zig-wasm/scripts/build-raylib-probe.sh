#!/usr/bin/env bash
# AI-assisted local probe; no jank or application code involved.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
MODE=${1:-wasm64}
bash "$ROOT/scripts/build-raylib.sh" "$MODE"
OUT="$ROOT/artifacts/raylib/$MODE"
if [[ "$MODE" == wasm64 ]]; then
  export EM_CONFIG="$ROOT/.tools/gc-wasm/emsdk/.emscripten"
  "$ROOT/.tools/gc-wasm/emsdk/upstream/emscripten/emcc" -O2 -fwasm-exceptions \
    -sMEMORY64=1 -sUSE_GLFW=3 -sMAX_WEBGL_VERSION=2 -sALLOW_MEMORY_GROWTH=1 \
    -sEXIT_RUNTIME=0 -I"$OUT/include" "$ROOT/raylib/probe.c" \
    "$OUT/lib/libraygui.a" "$OUT/lib/libraylib.a" -o "$OUT/probe.js"
  cp "$ROOT/raylib/probe.html" "$OUT/index.html"
else
  docker exec --user "$(id -u):$(id -g)" jank-host-build gcc -O2 -I"$OUT/include" \
    "$ROOT/raylib/probe.c" "$OUT/lib/libraygui.a" "$OUT/lib/libraylib.a" \
    -lGL -lm -lpthread -ldl -lrt -lX11 -o "$OUT/probe"
fi
echo "PROBE LINK $MODE: PASS"
