#!/usr/bin/env bash
# AI-assisted Pages assembly; does not commit, push or install host packages.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
./jank-build build examples/live-demo
./jank-build build examples/pacman
OUT="$ROOT/artifacts/pages/jank-wasm"
mkdir -p "$ROOT/artifacts/pages"
STAGE=$(mktemp -d "$ROOT/artifacts/pages/.stage-XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
cp site/index.html site/pacman.html site/style.css site/runner.js site/pacman-runner.js "$STAGE/"
cp artifacts/app/live/wasm/live.js artifacts/app/live/wasm/live.wasm "$STAGE/"
cp artifacts/app/pacman/wasm/pacman.js artifacts/app/pacman/wasm/pacman.wasm "$STAGE/"
cp examples/pacman/LICENSE "$STAGE/pacman-LICENSE"
cp examples/pacman/NOTICE.md "$STAGE/pacman-NOTICE.md"
cargo build --quiet --release --locked --manifest-path tools/site-highlight/Cargo.toml \
  --target-dir "$ROOT/artifacts/site-highlight"
artifacts/site-highlight/release/site-highlight "$STAGE/index.html"
touch "$STAGE/.nojekyll"
rm -rf "$OUT"
mv "$STAGE" "$OUT"
printf 'Pages site assembled: %s\n' "$OUT"
