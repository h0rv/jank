#!/usr/bin/env bash
# AI-assisted research driver; run inside the documented Ubuntu container.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
SOURCE="$(cd ../.. && pwd)/compiler+runtime"
LLVM_PREFIX="${LLVM_PREFIX:-/usr/lib/llvm-23}"
JOBS="${JOBS:-6}"
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export TMPDIR="$ROOT/artifacts/tmp"
export XDG_CACHE_HOME="$ROOT/.tools/host-cache"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" artifacts/logs
HOST="$ROOT/artifacts/build-host"
TARGET="$ROOT/artifacts/build-target"
RESOURCES="$ROOT/artifacts/host-resources"
mkdir -p "$RESOURCES"
ln -sfn "$SOURCE/src" "$RESOURCES/src"
ln -sfn "$SOURCE/include/cpp" "$RESOURCES/include"
ln -sfn "$HOST" "$RESOURCES/lib"
common=(-GNinja -DCMAKE_BUILD_TYPE=Release
  "-DCMAKE_C_COMPILER=$LLVM_PREFIX/bin/clang"
  "-DCMAKE_CXX_COMPILER=$LLVM_PREFIX/bin/clang++"
  "-Dllvm_dir=$LLVM_PREFIX" "-Dclang_dir=$LLVM_PREFIX"
  "-Djank_resource_dir=$RESOURCES" -Djank_install_local_clang=OFF)
run() {
  local name=$1
  shift
  local start=$SECONDS status=0
  "$@" > "artifacts/logs/host-$name.log" 2>&1 || status=$?
  printf '%s: exit=%s elapsed=%ss\n' "$name" "$status" "$((SECONDS-start))" |
    tee "artifacts/logs/host-$name.result"
  tail -n 15 "artifacts/logs/host-$name.log"
  return "$status"
}
case "${1:-host}" in
  host)
    run configure cmake -S "$SOURCE" -B "$HOST" "${common[@]}" \
      -Djank_test=ON "-DCMAKE_INSTALL_PREFIX=$ROOT/.tools/host-install"
    run build cmake --build "$HOST" -j "$JOBS"
    ;;
  test) run test bash -c 'cd "$1" && "$2/jank-test"' _ "$SOURCE" "$HOST" ;;
  spike)
    export JANK="$HOST/jank" ZIG="$ROOT/.tools/zig-x86_64-linux-0.17.1/zig"
    export ZIG_GLOBAL_CACHE_DIR="$ROOT/.zig-cache/global"
    run spike bash scripts/check-jank.sh
    ;;
  target)
    run target-configure cmake -S "$SOURCE" -B "$TARGET" "${common[@]}" \
      -Djank_cross_compile=ON "-Djank_host_compiler=${HOST_COMPILER:-$HOST/jank-phase-1}" \
      "-DCMAKE_INSTALL_PREFIX=$ROOT/.tools/target-install"
    run target-build cmake --build "$TARGET" -j "$JOBS" \
      --target jank_standalone_static_lib_phase_2
    ;;
  target-spike)
    mkdir -p artifacts/target-resources
    ln -sfn "$ROOT/.tools/host-install/lib/jank/0.1/include" artifacts/target-resources/include
    ln -sfn "$TARGET" artifacts/target-resources/lib
    export JANK="$HOST/jank" ZIG="$ROOT/.tools/zig-x86_64-linux-0.17.1/zig"
    export ZIG_GLOBAL_CACHE_DIR="$ROOT/.zig-cache/global"
    export JANK_RUNTIME_DIR="$ROOT/artifacts/target-resources"
    run target-spike bash scripts/check-jank-zig-cpp.sh
    ;;
  install) run install cmake --install "$HOST" ;;
  target-install) run target-install cmake --install "$TARGET" ;;
  *) echo "Usage: $0 {host|test|spike|target|install|target-install|target-spike}" >&2; exit 2 ;;
esac
