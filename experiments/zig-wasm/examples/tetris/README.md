# Fork-only Tetris research example

Copied from https://github.com/djblue/tetris at commit
`798780285f039ef7402acfc00b5b367820f818af` (`src/tetris/core.cljc` and
`src/tetris/main.jank`). Upstream has **no license**. This example is kept
in this research fork only, pending the author's permission. It is **not
for publishing**, public page deployment or redistribution. The source URL
is attribution, not a license grant. Raylib and raygui have separate zlib
licenses retained by their build recipe.

AI-assisted changes to the frontend: factor one loop iteration into `frame`,
keep the native loop/CloseWindow behind `:native`, and let Wasm initialization
return to the browser driver. Keep `SetTargetFPS` native-only: browser RAF
owns pacing, avoiding a second busy-wait in raylib's `EndDrawing`.
Print an initialization marker. The shared
`core.cljc` is byte-for-byte unchanged. Portal/tap development code is retained.

From `experiments/zig-wasm`:

```sh
./jank-build build examples/tetris
./jank-build serve examples/tetris  # loopback only, do not publish
node scripts/check-tetris-browser.mjs
```

The interactive frontend starts at a raygui START button. Click it to play;
arrows move/rotate, Space drops, C holds, Escape pauses. Enter/Space do not
activate the upstream welcome menu; the browser check also clicks START.
The app retains its own native loop; browser frames use the driver's
empty-stack GC safepoints. See the experiment README for limitations.

## Bounded local measurements

Chrome 156, SwiftShader/WebGL2, Emscripten 7.0.0 memory64, 1280×800 canvas:

| Cadence | 10-second frame rate | Collections |
| --- | ---: | ---: |
| Every frame (selected default) | 59.81 FPS | 599 |
| Every 10 frames | 60.03 FPS | 60 |

Both are approximately the 60 Hz RAF limit in an otherwise idle run. Select
every-frame collection for lower between-collection allocation and simpler
lifetime boundaries, not a claimed performance win. Concurrent compiler load
reduced earlier measurements to 54–57 FPS; these are local, not portable
performance guarantees. Wasm omits raylib's own target-FPS wait to avoid
double pacing.

During a further 63.67 seconds of arrow/Space input with collection every
frame, 3,789 frames ran. Linear memory stayed at 71,106,560 bytes (zero growth);
GC heap stayed at 59,383,808 bytes. Used GC bytes moved from 27,103,232 to
27,041,792. The starting sample followed the 10-frame cadence comparison.
This bounds this session only, not an all-input or long-term leak proof.
The GC reports heap growth during disabled-GC initialization; the post-init
play measurements above do not include that one-time startup allocation.

The script saves welcome, started, input and final screenshots, pixel hashes,
WebGL errors, exception counts and per-second memory samples in ignored
`artifacts/logs/tetris/headless/`. It sends Enter/Space, clicks the upstream
raygui Start button, then sends arrows and Space; both startup and gameplay
produce distinct rendered hashes. `--headed` runs the short input check on
the desktop and also saves `headed/desktop.png` (requires ImageMagick `import`).
Native rendering was checked under Xvfb for 12 seconds, terminated by the
test timeout (124), with `artifacts/logs/tetris-native.png` saved while live.
