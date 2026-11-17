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
