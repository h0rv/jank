#!/usr/bin/env bash
# AI-assisted research builds; no host packages or global SDK changes.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
MODE=${1:-}
case "$MODE" in native|wasm64) ;; *) echo "Usage: $0 native|wasm64" >&2; exit 2;; esac
SDK="$ROOT/.tools/gc-wasm/emsdk"
BASE="$ROOT/artifacts/raylib"
OUT="$BASE/$MODE"
mkdir -p "$BASE/downloads" "$OUT/include" "$OUT/lib" "$ROOT/artifacts/logs/raylib"
exec > >(tee "$ROOT/artifacts/logs/raylib/$MODE-build.log") 2>&1
fetch() {
  local url=$1 file=$2 digest=$3
  if [[ ! -f "$file" ]]; then
    curl -fL --retry 2 "$url" -o "$file.part.$$"
    printf '%s  %s\n' "$digest" "$file.part.$$" | sha256sum -c -
    mv "$file.part.$$" "$file"
  fi
  printf '%s  %s\n' "$digest" "$file" | sha256sum -c -
}
fetch https://github.com/raysan5/raylib/archive/refs/tags/6.0.tar.gz \
  "$BASE/downloads/raylib-6.0.tar.gz" 2b3ee1e2120c7a0796b33062c7e9a694dd8a8caa56a96319ac8c8ecf54a90d0b
fetch https://repo.clojars.org/org/jank-lang/commons/raygui-sys/2026.09-5/raygui-sys-2026.09-5.jar \
  "$BASE/downloads/raygui-sys-2026.09-5.jar" 7b0afddaef0fb1a6e3150d69a1450852af937ea559073650d0e5630128f765a1
STAMP=$(sha256sum "$0" "$ROOT"/raylib/patches/*.patch | cut -d' ' -f1 | sha256sum | cut -d' ' -f1)
if [[ -f "$OUT/stamp" && $(<"$OUT/stamp") == "$STAMP" && -f "$OUT/lib/libraylib.a" && -f "$OUT/lib/libraygui.a" ]]; then
  echo "CACHED: $OUT (include/ and lib/)"
  exit 0
fi
rm -rf "$OUT/source"
mkdir -p "$OUT/source"
tar -xzf "$BASE/downloads/raylib-6.0.tar.gz" -C "$OUT/source"
unzip -q "$BASE/downloads/raygui-sys-2026.09-5.jar" -d "$OUT/source/raygui-sys"
SRC="$OUT/source/raylib-6.0"
for patch in "$ROOT"/raylib/patches/*.patch; do patch -d "$SRC" -p1 < "$patch"; done
cp "$SRC"/src/{raylib.h,raymath.h,rlgl.h} "$OUT/include/"
cp "$OUT/source/raygui-sys/lib/raygui/src/raygui.h" "$OUT/include/"
cp "$SRC/LICENSE" "$OUT/raylib-LICENSE"
cp "$OUT/source/raygui-sys/lib/raygui/LICENSE" "$OUT/raygui-LICENSE"
if [[ "$MODE" == wasm64 ]]; then
  export PATH="$SDK/upstream/emscripten:$PATH" EM_CONFIG="$SDK/.emscripten"
  make -C "$SRC/src" -j4 PLATFORM=PLATFORM_WEB GRAPHICS=GRAPHICS_API_OPENGL_ES3 \
    CUSTOM_CFLAGS='-sMEMORY64=1 -fwasm-exceptions'
  cp "$SRC/src/libraylib.web.a" "$OUT/lib/libraylib.a"
  emcc -O2 -sMEMORY64=1 -fwasm-exceptions -I"$OUT/include" \
    -c "$OUT/source/raygui-sys/raygui_impl.c" -o "$OUT/raygui.o"
  emar rcs "$OUT/lib/libraygui.a" "$OUT/raygui.o"
else
  if ! docker exec jank-host-build pkg-config --exists x11 xrandr xi xinerama xcursor gl; then
    docker exec jank-host-build bash -c 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y libx11-dev libxrandr-dev libxi-dev libxinerama-dev libxcursor-dev libgl1-mesa-dev'
  fi
  docker exec --user "$(id -u):$(id -g)" jank-host-build \
    make -C "$SRC/src" -j4 PLATFORM=PLATFORM_DESKTOP CUSTOM_CFLAGS=-fPIC
  cp "$SRC/src/libraylib.a" "$OUT/lib/libraylib.a"
  docker exec --user "$(id -u):$(id -g)" jank-host-build gcc -O2 -fPIC -I"$OUT/include" \
    -c "$OUT/source/raygui-sys/raygui_impl.c" -o "$OUT/raygui.o"
  docker exec --user "$(id -u):$(id -g)" jank-host-build ar rcs "$OUT/lib/libraygui.a" "$OUT/raygui.o"
fi
printf '%s\n' "$STAMP" > "$OUT/stamp"
echo "BUILT $MODE: $OUT (include/ and lib/)"
