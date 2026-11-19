#!/usr/bin/env bash
# AI-assisted, experiment-local Linux x86_64 toolchain pins.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
P="$ROOT/artifacts/wasi-probes"
SOURCES="$ROOT/wasi-probe"
L="$ROOT/artifacts/logs/wasi"
S="$ROOT/.tools/wasi/wasi-sdk-34.0-x86_64-linux"
B="$ROOT/.tools/wasi/binaryen-version_133/bin"
W="$ROOT/.tools/wasi/wasmtime-v50.0.2-x86_64-linux/wasmtime"
NODE="$ROOT/.tools/node-v26.13.1-linux-x64/bin/node"
features=(--enable-memory64 --enable-exception-handling --enable-bulk-memory
  --enable-mutable-globals --enable-nontrapping-float-to-int --enable-sign-ext
  --enable-reference-types --enable-multivalue)

wasi_tools() {
  if [[ "$(uname -s)-$(uname -m)" != Linux-x86_64 ]]; then
    echo 'The pinned WASI probe toolchains require Linux x86_64.' >&2
    return 1
  fi
  mkdir -p "$ROOT/.tools/wasi" "$P" "$L" "$ROOT/artifacts/tmp"
  export TMPDIR="$ROOT/artifacts/tmp"
  wasi_download "$S/bin/clang" wasi-sdk-34.0.tar.gz \
    https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-34/wasi-sdk-34.0-x86_64-linux.tar.gz \
    b761e3a0721dbae9c09a0059e5fdb2bf917d1b4a8a7b430fb3b5aafb0984b2c4
  wasi_download "$W" wasmtime-50.0.2.tar.xz \
    https://github.com/bytecodealliance/wasmtime/releases/download/v50.0.2/wasmtime-v50.0.2-x86_64-linux.tar.xz \
    5db0ca8e838ab95a51ba9acdf11f42888bcd0092dda45a86129ae540c4fa952c
  wasi_download "$B/wasm-merge" binaryen-133.tar.gz \
    https://github.com/WebAssembly/binaryen/releases/download/version_133/binaryen-version_133-x86_64-linux.tar.gz \
    2dc9c7813f5375db93d96ead4b78222fcc3e2677bbb832297af4797782a37489
}

wasi_download() {
  local executable=$1 archive="$ROOT/.tools/wasi/$2" url=$3 digest=$4
  if [[ ! -x "$executable" ]]; then
    curl -fL --retry 2 "$url" -o "$archive"
    printf '%s  %s\n' "$digest" "$archive" | sha256sum -c -
    tar -xf "$archive" -C "$ROOT/.tools/wasi"
  fi
}

wasi_compile_shim() {
  "$S/bin/clang" --target=wasm64-wasip1 -O2 -g -fno-builtin -nostdlib \
    -Wl,--no-entry -Xlinker --import-memory=main,memory \
    "$SOURCES/wasi64-shim.c" -o "$P/wasi64-shim.wasm"
}
