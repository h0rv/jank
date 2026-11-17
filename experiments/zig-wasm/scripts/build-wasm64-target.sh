#!/usr/bin/env bash
# AI-assisted blocker probe; run inside the documented Ubuntu 24.04 container.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
SOURCE="$(cd ../.. && pwd)/compiler+runtime"
SDK="${EMSDK:-$ROOT/.tools/gc-wasm/emsdk}"
BUILD="$ROOT/artifacts/build-wasm64"
HEADERS="$ROOT/.tools/wasm64-headers"
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export TMPDIR="$ROOT/artifacts/tmp" XDG_CACHE_HOME="$ROOT/.tools/host-cache"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" artifacts/logs
export PATH="$SDK/upstream/emscripten:$SDK/upstream/bin:$PATH"
export EM_CONFIG="$SDK/.emscripten"
run() {
  local name=$1 status=0 start=$SECONDS
  shift
  "$@" > "artifacts/logs/wasm64-$name.log" 2>&1 || status=$?
  printf '%s: exit=%s elapsed=%ss\n' "$name" "$status" "$((SECONDS-start))" |
    tee "artifacts/logs/wasm64-$name.result"
  tail -n 20 "artifacts/logs/wasm64-$name.log"
  return "$status"
}
case "${1:-configure}" in
  deps)
    run deps "$SDK/upstream/emscripten/embuilder" build zlib boost_headers --wasm64
    mkdir -p "$HEADERS"
    for header in boost zlib.h zconf.h; do
      ln -sfn "$SDK/upstream/emscripten/cache/sysroot/include/$header" "$HEADERS/$header"
    done
    ;;
  configure)
    # Compile the real unwind backend for diagnostics even when its probe fails.
    run configure emcmake cmake -S "$SOURCE" -B "$BUILD" -GNinja \
      -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
      -DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON \
      -DCMAKE_C_FLAGS='-sMEMORY64=1 -fwasm-exceptions' \
      -DCMAKE_CXX_FLAGS='-sMEMORY64=1 -fwasm-exceptions' \
      -DCMAKE_EXE_LINKER_FLAGS='-sMEMORY64=1 -fwasm-exceptions' \
      -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
      -DCMAKE_FIND_PACKAGE_PREFER_CONFIG=ON \
      -Dllvm_dir=/usr/lib/llvm-23 -Dclang_dir=/usr/lib/llvm-23 \
      -Dzstd_DIR=/usr/lib/x86_64-linux-gnu/cmake/zstd \
      -Djank_cross_compile=ON -Djank_emulated_tls=OFF -Denable_threads=OFF \
      -DCPPTRACE_UNWIND_WITH_UNWIND=ON \
      "-DZLIB_LIBRARY=$SDK/upstream/emscripten/cache/sysroot/lib/wasm64-emscripten/libz.a" \
      "-DZLIB_INCLUDE_DIR=$HEADERS" "-DBoost_INCLUDE_DIR=$HEADERS" \
      "-Djank_host_compiler=$ROOT/artifacts/build-host/jank-phase-1" \
      "-Djank_resource_dir=$ROOT/artifacts/host-resources" \
      -Djank_install_local_clang=OFF
    ;;
  build)
    run build cmake --build "$BUILD" -j "${JOBS:-6}" \
      --target jank_standalone_static_lib_phase_2 -- -k 0
    ;;
  *) echo "Usage: $0 {deps|configure|build}" >&2; exit 2 ;;
esac
