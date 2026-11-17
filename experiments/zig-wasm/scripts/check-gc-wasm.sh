#!/usr/bin/env bash
# Isolated memory64 Boehm experiment. No global installs or source patches.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
TOOLS="$ROOT/.tools/gc-wasm"
OUT="$ROOT/artifacts/gc-wasm"
GC_REV=91f30f37b0457566e9823b8360da59f1798f65fc
EMSDK_REV=708dcbcc9ee23bc7d2dad44fc90db377e38b771c
SDK_VERSION=7.0.0
GC="$TOOLS/bdwgc-$GC_REV"
SDK="$TOOLS/emsdk"
NODE_BIN=${NODE_BIN:-$(command -v node)}
MODE=${1:-all}
case "$MODE" in all|spill|asyncify|explicit) ;; *) echo "Usage: $0 [all|spill|asyncify|explicit]" >&2; exit 2;; esac
mkdir -p "$TOOLS" "$OUT"

if [[ ${BOOTSTRAP:-0} == 1 ]]; then
  if [[ ! -f "$GC/extra/gc.c" ]]; then
    curl -fL --max-time 30 "https://codeload.github.com/bdwgc/bdwgc/tar.gz/$GC_REV" -o "$TOOLS/bdwgc.tar.gz"
    tar -xzf "$TOOLS/bdwgc.tar.gz" -C "$TOOLS"
  fi
  if [[ ! -f "$SDK/emsdk" ]]; then
    git clone --no-checkout https://github.com/emscripten-core/emsdk.git "$SDK"
    git -C "$SDK" checkout --detach "$EMSDK_REV"
  fi
  "$SDK/emsdk" install "$SDK_VERSION" > "$OUT/emsdk-install.log" 2>&1
  "$SDK/emsdk" activate "$SDK_VERSION" > "$OUT/emsdk-activate.log" 2>&1
fi
EMCC="$SDK/upstream/emscripten/emcc"
EMXX="$SDK/upstream/emscripten/em++"
if [[ ! -x "$EMCC" || ! -f "$GC/extra/gc.c" ]]; then
  echo "Missing local SDK/source. Run BOOTSTRAP=1 bash $0 $MODE" >&2
  exit 2
fi
"$NODE_BIN" --version
"$EMCC" --version

build_and_run() {
  local mode=$1
  local -a gc_flags=() link_flags=() client_flags=()
  case "$mode" in
    spill) link_flags=(-sBINARYEN_EXTRA_PASSES=--spill-pointers) ;;
    asyncify)
      gc_flags=(-DEMSCRIPTEN_ASYNCIFY)
      link_flags=(-sASYNCIFY -sASYNCIFY_STACK_SIZE=128000)
      ;;
    explicit) client_flags=(-DGC_EXPLICIT_ROOTS) ;;
  esac
  "$EMCC" -O2 -m64 -DGC_NOT_DLL -DNO_EXECUTE_PERMISSION \
    -DALL_INTERIOR_POINTERS ${gc_flags[@]+"${gc_flags[@]}"} -I"$GC/include" \
    -c "$GC/extra/gc.c" -o "$OUT/gc-$mode.o" || return $?
  "$EMXX" -O2 -std=c++17 -m64 -sALLOW_MEMORY_GROWTH=1 \
    -sENVIRONMENT=node ${link_flags[@]+"${link_flags[@]}"} ${client_flags[@]+"${client_flags[@]}"} \
    -I"$GC/include" "$ROOT/wasm-probe/gc-smoke.cpp" "$OUT/gc-$mode.o" \
    -o "$OUT/gc-$mode.cjs" || return $?
  "$NODE_BIN" "$OUT/gc-$mode.cjs"
}

failed=0
modes=("$MODE")
if [[ "$MODE" == all ]]; then modes=(spill asyncify explicit); fi
: > "$OUT/results.txt"
for mode in "${modes[@]}"; do
  # Asyncify can defer main's return. Require the final success marker too.
  if build_and_run "$mode" > "$OUT/$mode.log" 2>&1 &&
      grep -q '^PASS: wasm64,' "$OUT/$mode.log"; then
    printf '%s: PASS (see %s/%s.log)\n' "$mode" "$OUT" "$mode" | tee -a "$OUT/results.txt"
  else
    status=$?
    printf '%s: FAIL exit=%s (see %s/%s.log)\n' "$mode" "$status" "$OUT" "$mode" | tee -a "$OUT/results.txt"
    failed=1
  fi
done
# Do not report success when either automatic-root strategy failed.
exit "$failed"
