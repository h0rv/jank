#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"
SDK=${EMSDK:-/home/ubuntu/tools/emsdk}
BIN="$SDK/upstream/bin"
OUT=../artifacts/wasm-gc-probe
mkdir -p "$OUT"
"$BIN/clang" --version
"$SDK/upstream/emscripten/emcc" --version
"$BIN/clang" --target=wasm32 -mcpu=help
"$BIN/clang" --target=wasm32 -mgc -mreference-types -dM -E -x c /dev/null | rg '__wasm_(gc|reference_types)'
"$BIN/clang" --target=wasm32 -mgc -mreference-types -O2 -nostdlib -Wl,--no-entry -Wl,--export=read_cell linear.cpp -o "$OUT/linear.wasm"
"$BIN/wasm-dis" "$OUT/linear.wasm"
"$BIN/wasm-opt" --version
"$BIN/wasm-opt" --help | rg -- '--(enable-gc|gsi |gto |gufa |heap2local |remove-unused-types)'
"$BIN/wasm-opt" "$OUT/gc.wasm" --enable-gc --enable-reference-types --closed-world --gsi --gto --heap2local -o "$OUT/gc-optimized.wasm"
echo 'Binaryen GC passes: exit=0'
test -x "$BIN/llc" && "$BIN/llc" -mtriple=wasm32 -mattr=help || echo 'llc not shipped by emsdk; used clang feature macros and real codegen instead'
