#!/usr/bin/env bash
# AI-assisted preparation of a separate browser frame-loop project.
set -euo pipefail
cd "$(dirname "$0")/../.."
example=examples/flappy-bird
gc=${1:-between-frames}
case "$gc" in between-frames|spill) ;; *) echo "Expected between-frames or spill" >&2; exit 2 ;; esac
name=flappy-frame-$gc
project=artifacts/frame-gc/$name
mkdir -p "$project/src/flappy_frame"
cp "$example"/frame-loop.jank "$project/src/flappy_frame/loop.jank"
cp -R "$example"/vendor/src/. "$project/src/"
cat > "$project/jank-build.json" <<EOF
{
  "name": "$name",
  "main": "flappy-frame.loop",
  "libraries": ["raylib"],
  "frame": "flappy-frame.loop/frame",
  "expect": ["flappy-frame: initialized"],
  "wasm": {"gc": "$gc"}
}
EOF
./jank-build build "$project"
