#!/usr/bin/env bash
# AI-assisted bounded toolchain probes; not a jank distribution portability test.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
ZIG="${ZIG:-$ROOT/.tools/zig-x86_64-linux-0.17.1/zig}"
NODE="$ROOT/.tools/node-v26.13.1-linux-x64/bin/node"
OUT="$ROOT/artifacts/zig-toolchain-probe"
mkdir -p "$OUT" "$ROOT/artifacts/logs"
exec > >(tee "$ROOT/artifacts/logs/zig-toolchain-probe.log") 2>&1
test "$("$ZIG" version)" = 0.17.1
export ZIG_GLOBAL_CACHE_DIR="$ROOT/.zig-cache/global"
export PATH="$(dirname "$NODE"):$PATH"
unset EMSDK EM_CONFIG SYSROOT C_INCLUDE_PATH CPLUS_INCLUDE_PATH
set -x
"$ZIG" test native.zig -O ReleaseSafe --cache-dir "$OUT/cache"
"$ZIG" build-obj native.zig -O ReleaseSafe -femit-bin="$OUT/native.o" --cache-dir "$OUT/cache"
file "$OUT/native.o"
ZIG="$ZIG" bash scripts/check-cpp-zig-wasm.sh

cat > "$OUT/glibc228.cpp" <<'CPP'
#include <cstdio>
#include <vector>
int main() {
    const std::vector<int> values{10, -3, 20, 15};
    int sum = 0;
    for (int value : values) sum += value;
    std::printf("glibc-2.28 C++ sum: %d\n", sum);
    return sum == 42 ? 0 : 1;
}
CPP
ZIG_LOCAL_CACHE_DIR="$OUT/cache" "$ZIG" c++ -target x86_64-linux-gnu.2.28 -std=c++20 -O2 \
  "$OUT/glibc228.cpp" -o "$OUT/glibc228"
"$OUT/glibc228"
readelf --version-info "$OUT/glibc228"
echo 'Toolchain probes passed; no older-glibc host or complete jank rebuild was tested.'
