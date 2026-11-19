# Flappy Bird

An AI-assisted build integration for [jank's official flappy-bird example](https://github.com/jank-lang/jank/tree/a013d8dfe6b6ab18618ac20d73a5e99f50af2433/example/gui/flappy-bird).
`vendor/` contains every file from that directory at upstream commit
`a013d8dfe6b6ab18618ac20d73a5e99f50af2433`, byte-identical, including its
MPL-2.0 LICENSE and project.clj. No example source is modified. `upstream.sha256`
records the vendored file digests; verify from this directory with
`sha256sum -c upstream.sha256`. Builds need no network fetch of the example.

From the experiment directory:

```sh
./jank-build build examples/flappy-bird
bash examples/flappy-bird/check-native.sh
./jank-build serve examples/flappy-bird
```

Click New game, then hold Space to rise and release to fall. P pauses; Enter
returns to the menu after game over. The upstream main menu is static. Focus
the canvas for keyboard controls.

## Browser integration

The example's original blocking loop and SetTargetFPS remain intact. Raylib
6.0's web WindowShouldClose already calls emscripten_sleep(12); jank-build uses
Emscripten JSPI to suspend and resume that call without blocking the browser.
There are no reader conditionals or browser-specific changes in the source.
The build-system adapter registers static GC roots and wraps EndDrawing only
to report rendered-frame statistics to the page. Normal GC remains enabled;
the existing spill transform protects live references. This route requires
memory64, Wasm exceptions, JSPI and WebGL2 (Chrome 156 tested). It is not a
claim that every jank application or browser is supported.

## JSPI suspend guard

While main is suspended in emscripten_sleep, browser callbacks (GLFW input,
resize, focus) re-enter Wasm synchronously on the same linear-memory stack,
below the suspended stack pointer. Emscripten 7.0.0 wraps only main as a
promising export, so a callback that reached emscripten_sleep would trap with
a JSPI SuspendError rather than start a second suspended stack. Nothing in the
JSPI runtime checks that callbacks leave the suspended frames, including the
spill slots of the suspended jank frames, untouched.

jank-build links `scripts/jspi-suspend-guard.js` over emscripten_sleep
(`-Wl,--wrap=emscripten_sleep`). The guard is the Suspending import itself, so
it has no linear-memory frame inside the checked range. It copies
`[sp, stack base)` before suspending and aborts with `JSPI SUSPEND GUARD: ...`
if the stack pointer or any of those bytes differ on resume, or if a second
suspension starts while one is active. A first version written in C gave false
positives: the spill pass gave its frame slots that it rewrote after resuming.

```sh
node scripts/check-jspi-suspend.mjs
```

The check floods the canvas with key, mouse, wheel, focus and resize events
for 20 seconds (`JSPI_STRESS_SECONDS`), then flips one byte just below the
suspended stack pointer (must not fire) and one byte inside the suspended
frames (must fire). Chrome 156 headless result:

| Phase | Result |
| --- | --- |
| Stress, 20 s | 3480 CDP events, 1043 frames, 1043 suspensions, no guard failure; suspended stack 53840 bytes |
| Write at sp-64 | no failure |
| Write at sp+26920 | abort: suspended stack frames were overwritten (1 bytes, first at sp+26920) |

The nested-suspension branch has no negative control: no page callback can
reach emscripten_sleep. The guard copies about 54 KB per frame. It does not
cover generic frame projects, which use emscripten_set_main_loop without JSPI.

Raylib and raygui are supplied by jank-build's raylib support; their zlib
licenses are retained by the build recipe. Upstream loads no external images,
fonts, sounds or other asset files; all drawing uses library primitives.
No preload archive or separate asset attribution is needed.

The bounded native smoke checks window/font/shader initialization and that
the process stays alive until the test timeout. Browser checks cover menu,
starting, held/released Space, scrolling, runtime errors and frame cadence.
Full playthroughs, long-duration memory behavior and non-Chrome browsers
remain unverified. This is a fork-only browser integration, not an upstream
supported browser release.

## Between-frame GC

The default browser build still uses JSPI and the spill pass. The separate
AI-assisted experiment driver uses the vendored game's state transitions and
rendering unchanged, but stores the state in a rooted var and returns from
each frame to the browser instead of suspending inside the original loop.
Collection is a separate Wasm call from the browser.
Use the original example above for native play.

```sh
# From experiments/jank-wasm
bash examples/flappy-bird/build-frame-loop.sh
./jank-build serve artifacts/frame-gc/flappy-frame-between-frames
node scripts/measure-flappy-gc.mjs artifacts/app/flappy-frame-between-frames/wasm/flappy-frame-between-frames.js
STRESS=1 PLAY_SECONDS=60 STARTUP_RUNS=1 node scripts/measure-flappy-gc.mjs \
  artifacts/app/flappy-frame-between-frames/wasm/flappy-frame-between-frames.js
```

Pass `spill` to `build-frame-loop.sh` to build the same returning-frame driver
with the spill transform. The Chrome harness sets 30 frames between collections
for both returning variants unless `COLLECT_EVERY` is set.
