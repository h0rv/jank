#!/usr/bin/env bash
# AI-assisted native wasm32-wasip1 runtime build; run in jank-host-build.
set -euo pipefail
source "$(dirname "$0")/wasi-tools.sh"
cd "$ROOT"
SOURCE="$(cd ../.. && pwd)/compiler+runtime"
BUILD="$ROOT/artifacts/build-wasi32"
ZLIB="$ROOT/.tools/wasi/build-zlib"
HEADERS="$ROOT/.tools/wasi/headers"
TOOLCHAIN="$S/share/cmake/wasi-sdk-p1.cmake"
wasi32_features=(--enable-exception-handling --enable-bulk-memory
  --enable-mutable-globals --enable-nontrapping-float-to-int --enable-sign-ext
  --enable-reference-types --enable-multivalue)
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export TMPDIR="$ROOT/artifacts/tmp"
mkdir -p "$L" "$TMPDIR"
run() {
  local name=$1 rc=0; shift
  { printf '$ '; printf '%q ' "$@"; printf '\n'; "$@" || rc=$?; printf 'EXIT=%s\n' "$rc"; } \
    > "$L/wasi32-$name.log" 2>&1
  tail -n 20 "$L/wasi32-$name.log"
  return "$rc"
}
case "${1:-configure}" in
  tools) wasi_tools ;;
  deps)
    wasi_tools
    archive="$ROOT/.tools/wasi/zlib-1.3.2.tar.gz"
    if [[ ! -f "$archive" ]]; then
      run zlib-download curl -fL --retry 2 \
        https://github.com/madler/zlib/archive/refs/tags/v1.3.2.tar.gz -o "$archive"
    fi
    printf '%s  %s\n' \
      16fea4df307a68cf0035858abe2fd550250618a97590e202037acd18a666f57afc10f8836cbbd472d54a0e76539d0e558cb26f059d53de52ff90634bbf4f47d4 \
      "$archive" | sha512sum -c -
    if [[ ! -d "$ROOT/.tools/wasi/zlib-1.3.2" ]]; then
      tar -xf "$archive" -C "$ROOT/.tools/wasi"
    fi
    run zlib-configure cmake -S "$ROOT/.tools/wasi/zlib-1.3.2" -B "$ZLIB" -GNinja \
      "-DCMAKE_TOOLCHAIN_FILE=$TOOLCHAIN" -DCMAKE_BUILD_TYPE=Release \
      -DZLIB_BUILD_TESTING=OFF -DZLIB_BUILD_SHARED=OFF
    run zlib-build cmake --build "$ZLIB" --target zlibstatic -j "${JOBS:-6}"
    mkdir -p "$HEADERS"
    ln -sfn /usr/include/boost "$HEADERS/boost"
    ;;
  configure)
    run configure cmake -S "$SOURCE" -B "$BUILD" -GNinja \
      "-DCMAKE_TOOLCHAIN_FILE=$TOOLCHAIN" -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
      "-DCMAKE_C_FLAGS=-fwasm-exceptions -D_WASI_EMULATED_MMAN" \
      "-DCMAKE_CXX_FLAGS=-fwasm-exceptions -D_WASI_EMULATED_MMAN" \
      "-DCMAKE_EXE_LINKER_FLAGS=-lunwind -lwasi-emulated-mman" \
      -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
      -Dllvm_dir=/usr/lib/llvm-23 -Dclang_dir=/usr/lib/llvm-23 \
      -Dzstd_DIR=/usr/lib/x86_64-linux-gnu/cmake/zstd \
      -Dzstd_LIBRARY=/usr/lib/x86_64-linux-gnu/libzstd.so -Dzstd_INCLUDE_DIR=/usr/include \
      -Djank_cross_compile=ON -Djank_emulated_tls=OFF -Denable_threads=OFF \
      "-DZLIB_LIBRARY=$ZLIB/libz.a" "-DZLIB_INCLUDE_DIR=$ROOT/.tools/wasi/zlib-1.3.2" \
      "-DBoost_INCLUDE_DIR=$HEADERS" \
      "-Djank_host_compiler=$ROOT/artifacts/build-host/jank-phase-1" \
      "-Djank_resource_dir=$ROOT/artifacts/host-resources" -Djank_install_local_clang=OFF
    ;;
  build)
    run build cmake --build "$BUILD" -j "${JOBS:-6}" \
      --target jank_standalone_static_lib_phase_2 -- -k 0
    ;;
  components)
    run components cmake --build "$BUILD" -j "${JOBS:-6}" \
      --target jank_common_lib jank_static_lib jank_lib_phase_2 folly_lib gc gctba libzstd_static
    ;;
  capture)
    wasi_tools
    run capture-link "$S/bin/clang" --target=wasm32-wasip1 -O2 \
      "$SOURCES/capture.c" -o "$P/wasi32-capture.wasm"
    run capture-run "$W" run "$P/wasi32-capture.wasm"
    echo 'WASI32 CAPTURE VERDICT: unsupported descriptor duplication reproduced'
    ;;
  eh)
    wasi_tools
    run eh-link "$S/bin/clang++" --target=wasm32-wasip1 -O2 -fwasm-exceptions \
      "$SOURCES/hello.cpp" -lunwind -o "$P/wasi32-eh.wasm"
    run eh-exnref "$B/wasm-opt" "$P/wasi32-eh.wasm" "${wasi32_features[@]}" \
      --translate-to-exnref -o "$P/wasi32-eh-exnref.wasm"
    run eh-run "$W" run -W exceptions=y "$P/wasi32-eh-exnref.wasm"
    grep -Fxq 'C++ exception caught: 42' "$L/wasi32-eh-run.log"
    echo 'WASI32 EH VERDICT: PASS (isolated probe, not the jank runtime)'
    ;;
  *) echo "Usage: $0 {tools|deps|configure|build|components|capture|eh}" >&2; exit 2 ;;
esac
