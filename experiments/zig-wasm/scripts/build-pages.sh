#!/usr/bin/env bash
# AI-assisted Pages assembly; does not commit, push or install host packages.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
./jank-build build examples/hello-cljc
OUT="$ROOT/artifacts/pages/jank-wasm"
mkdir -p "$ROOT/artifacts/pages"
STAGE=$(mktemp -d "$ROOT/artifacts/pages/.stage-XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
cp site/index.html site/try.html site/style.css site/runner.js "$STAGE/"
cp artifacts/app/hello/wasm/hello.js artifacts/app/hello/wasm/hello.wasm "$STAGE/"
touch "$STAGE/.nojekyll"
rm -rf "$OUT"
mv "$STAGE" "$OUT"
printf 'Pages site assembled: %s\n' "$OUT"
