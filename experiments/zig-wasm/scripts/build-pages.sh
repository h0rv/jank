#!/usr/bin/env bash
# AI-assisted Pages assembly; does not commit, push or install host packages.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
./jank-build build examples/live-demo
OUT="$ROOT/artifacts/pages/jank-wasm"
mkdir -p "$ROOT/artifacts/pages"
STAGE=$(mktemp -d "$ROOT/artifacts/pages/.stage-XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
cp site/index.html site/style.css site/runner.js "$STAGE/"
cp artifacts/app/live/wasm/live.js artifacts/app/live/wasm/live.wasm "$STAGE/"
cargo build --quiet --release --locked --manifest-path tools/site-highlight/Cargo.toml \
  --target-dir "$ROOT/artifacts/site-highlight"
artifacts/site-highlight/release/site-highlight "$STAGE/index.html"
touch "$STAGE/.nojekyll"
rm -rf "$OUT"
mv "$STAGE" "$OUT"
printf 'Pages site assembled: %s\n' "$OUT"
