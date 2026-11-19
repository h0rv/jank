#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE=$(cd "$ROOT/../.." && pwd)/compiler+runtime
SDK=${EMSDK:-$ROOT/.tools/gc-wasm/emsdk}
NODE_BIN=${NODE_BIN:-node}
EM="$SDK/upstream/emscripten"
OUT="$ROOT/artifacts/exception-roots"

if [[ ! -x "$EM/em++" || ! -f "$SOURCE/third-party/bdwgc/extra/gc.c" ]]; then
  echo 'Initialize the pinned Emscripten SDK and bdwgc submodule first (see README).' >&2
  exit 2
fi

mkdir -p "$OUT"
GC=$(mktemp -d "$OUT/bdwgc.XXXXXX")
trap 'rm -rf "$GC"' EXIT
git -C "$SOURCE/third-party/bdwgc" archive HEAD | tar -x -C "$GC"
GIT_CEILING_DIRECTORIES="$OUT" git -C "$GC" apply "$SOURCE/cmake/dependency/bdwgc-wasm64.patch"

for bits in 32 64; do
  target=(--target="wasm$bits-unknown-emscripten")
  gc_flags=(-DGC_NOT_DLL -DNO_EXECUTE_PERMISSION -DALL_INTERIOR_POINTERS -DGC_ATOMIC_UNCOLLECTABLE)
  if [[ "$bits" == 64 ]]; then
    gc_flags+=(-DPOINTER_MASK=0x0000FFFFFFFFFFFF)
  fi
  "$EM/emcc" "${target[@]}" -O2 "${gc_flags[@]}" -I"$GC/include" \
    -c "$GC/extra/gc.c" -o "$OUT/gc$bits.o"
  cxx=("${target[@]}" -O2 -std=c++20 -fwasm-exceptions -I"$GC/include")
  "$EM/em++" "${cxx[@]}" -isystem "$EM/system/lib/libcxxabi/src" \
    -c "$ROOT/scripts/exception-roots.cpp" -o "$OUT/wrap$bits.o"
  for mode in control wrapped; do
    link=()
    if [[ "$mode" == wrapped ]]; then
      link=("$OUT/wrap$bits.o" -Wl,--wrap=__cxa_allocate_exception,--wrap=__cxa_free_exception)
    fi
    output="$OUT/wasm$bits-$mode.cjs"
    "$EM/em++" "${cxx[@]}" -sENVIRONMENT=node -sEXIT_RUNTIME=1 \
      -Wl,--wrap=GC_malloc_uncollectable,--wrap=GC_free \
      "$ROOT/wasm-probe/exception-roots.cpp" "$OUT/gc$bits.o" "${link[@]}" -o "$output"
    "$NODE_BIN" "$output" "$mode" | tee "$OUT/wasm$bits-$mode.log"
    grep -Fxq "PASS: wasm$bits exception roots ($mode)" "$OUT/wasm$bits-$mode.log"
  done
done
