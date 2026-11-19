#!/usr/bin/env bash
# AI-assisted isolated rebuild of the SDK 34 C++ runtimes with legacy Wasm EH.
set -euo pipefail
source "$(dirname "$0")/wasi-tools.sh"
BASE="$ROOT/.tools/wasi"
REV=895aa2c896ada719451be2e3673c83da8ddf1141
SRC="$BASE/llvm-project-$REV"
BUILD="$BASE/build-legacy-runtimes"
PREFIX="$BASE/legacy-runtimes"
export TMPDIR="$ROOT/artifacts/tmp"
mkdir -p "$BASE" "$TMPDIR" "$L"
fetch() {
  local file=$1 url=$2 digest=$3
  if [[ ! -f "$BASE/$file" ]]; then
    curl -fL --retry 2 "$url" -o "$BASE/$file"
  fi
  printf '%s  %s\n' "$digest" "$BASE/$file" | sha256sum -c -
}
case "${1:-configure}" in
  source)
    fetch llvm-sdk34.tar.gz "https://codeload.github.com/llvm/llvm-project/tar.gz/$REV" \
      b4525499be9ccd65a0da8c9efbeb59a5955130b302a190a51883727d8c5c7542
    if [[ ! -d "$SRC/runtimes" ]]; then
      tar -xzf "$BASE/llvm-sdk34.tar.gz" -C "$BASE" --wildcards \
        "llvm-project-$REV/cmake/*" "llvm-project-$REV/runtimes/*" \
        "llvm-project-$REV/libcxx/*" "llvm-project-$REV/libcxxabi/*" \
        "llvm-project-$REV/libunwind/*" "llvm-project-$REV/llvm/cmake/*" \
        "llvm-project-$REV/llvm/include/*"
    fi
    if [[ ! -d "$SRC/llvm/utils/llvm-lit" ]]; then
      tar -xzf "$BASE/llvm-sdk34.tar.gz" -C "$BASE" --wildcards \
        "llvm-project-$REV/llvm/utils/*"
    fi
    if [[ ! -d "$SRC/libc/shared" ]]; then
      tar -xzf "$BASE/llvm-sdk34.tar.gz" -C "$BASE" --wildcards \
        "llvm-project-$REV/libc/*"
    fi
    patches=(llvm-pr-168449.patch llvm-pr-186054.patch llvm-undo-part-of-194317.patch)
    digests=(402310bd986400bb7419b11b59f877f1b1f4306f019347822cd4ee7fb5cb2c91
      4ed0d85e6280f37701a8a7b30c1750e61a9bec62cc7b040fd5338d90551811de
      bd901d86af8f1e000aa7efeb4e3d3677292fe07a106e817b09a0a67124a7ad00)
    for i in "${!patches[@]}"; do
      fetch "${patches[$i]}" "https://raw.githubusercontent.com/WebAssembly/wasi-sdk/wasi-sdk-34/src/${patches[$i]}" "${digests[$i]}"
    done
    if [[ ! -f "$SRC/.sdk-patches-applied" ]]; then
      for patch in "${patches[@]}"; do
        GIT_CEILING_DIRECTORIES="$BASE" git -C "$SRC" apply "$BASE/$patch"
      done
      touch "$SRC/.sdk-patches-applied"
    fi
    ;;
  configure)
    flags='-mcpu=lime1 -fwasm-exceptions -mllvm -wasm-use-legacy-eh=true'
    cmake -S "$SRC/runtimes" -B "$BUILD" -GNinja \
      "-DCMAKE_TOOLCHAIN_FILE=$S/share/cmake/wasi-sdk-p1.cmake" \
      "-DCMAKE_SYSROOT=$S/share/wasi-sysroot" -DCMAKE_BUILD_TYPE=Release \
      "-DCMAKE_INSTALL_PREFIX=$PREFIX" "-DCMAKE_STAGING_PREFIX=$PREFIX" \
      -DCMAKE_INSTALL_INCLUDEDIR=include/wasm32-wasip1/eh \
      "-DCMAKE_C_FLAGS=$flags" "-DCMAKE_CXX_FLAGS=$flags" "-DCMAKE_ASM_FLAGS=$flags" \
      -DCMAKE_POSITION_INDEPENDENT_CODE=OFF -DLLVM_COMPILER_CHECKED=ON \
      '-DLLVM_ENABLE_RUNTIMES=libunwind;libcxx;libcxxabi' \
      -DLIBCXX_ENABLE_THREADS=ON -DLIBCXX_HAS_PTHREAD_API=ON \
      -DLIBCXX_HAS_EXTERNAL_THREAD_API=OFF -DLIBCXX_HAS_WIN32_THREAD_API=OFF \
      -DLIBCXX_ENABLE_SHARED=OFF -DLIBCXX_ENABLE_EXCEPTIONS=ON \
      -DLIBCXX_ENABLE_FILESYSTEM=ON -DLIBCXX_ENABLE_ABI_LINKER_SCRIPT=OFF \
      -DLIBCXX_CXX_ABI=libcxxabi -DLIBCXX_HAS_MUSL_LIBC=OFF -DLIBCXX_ABI_VERSION=2 \
      -DLIBCXXABI_ENABLE_EXCEPTIONS=ON -DLIBCXXABI_ENABLE_SHARED=OFF \
      -DLIBCXXABI_SILENT_TERMINATE=ON -DLIBCXXABI_ENABLE_THREADS=ON \
      -DLIBCXXABI_HAS_PTHREAD_API=ON -DLIBCXXABI_HAS_EXTERNAL_THREAD_API=OFF \
      -DLIBCXXABI_HAS_WIN32_THREAD_API=OFF -DLIBCXXABI_USE_LLVM_UNWINDER=ON \
      -DLIBUNWIND_ENABLE_SHARED=OFF -DLIBUNWIND_ENABLE_THREADS=ON \
      -DLIBUNWIND_USE_COMPILER_RT=ON -DLIBUNWIND_INCLUDE_TESTS=OFF -DUNIX=ON \
      -DLIBCXX_LIBDIR_SUFFIX=/wasm32-wasip1/eh \
      -DLIBCXXABI_LIBDIR_SUFFIX=/wasm32-wasip1/eh \
      -DLIBUNWIND_LIBDIR_SUFFIX=/wasm32-wasip1/eh \
      -DLIBCXX_INCLUDE_TESTS=OFF -DLIBCXX_INCLUDE_BENCHMARKS=OFF
    ;;
  build) cmake --build "$BUILD" --target install -j "${JOBS:-6}" ;;
  *) echo "Usage: $0 {source|configure|build}" >&2; exit 2 ;;
esac
