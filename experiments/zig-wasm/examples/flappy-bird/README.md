# Flappy Bird

AI-assisted browser/native adaptation of [jank's official flappy-bird
example](https://github.com/jank-lang/jank/tree/a013d8dfe6b6ab18618ac20d73a5e99f50af2433/example/gui/flappy-bird),
upstream commit `a013d8dfe6b6ab18618ac20d73a5e99f50af2433`.
The upstream MPL-2.0 license is retained in LICENSE. Modified source is
available in this directory under the same license. This is a research-fork
port, not an upstream-supported browser release.

The game uses raylib and raygui, supplied by jank-build's raylib support
(their zlib licenses are retained in the raylib build recipe). All graphics
are procedural; upstream loads no images, fonts, sounds or other asset files,
so no preload archive or additional asset license is needed.

From the experiment directory:

```sh
./jank-build build examples/flappy-bird
bash examples/flappy-bird/check-native.sh
./jank-build serve examples/flappy-bird
```

Click the canvas or press Space to start. Hold Space or the left mouse button
to rise; release to fall. P pauses; Enter returns to the menu after game over.
The menu bird bobs automatically before input. Focus the canvas for keyboard
controls. Browser builds need memory64, Wasm exceptions and WebGL2.

## Changes from upstream

- Extract one iteration into `frame`, keep state in an atom and leave native
  looping, pacing and window cleanup behind a compile-time C++ bridge.
  Browser RAF owns pacing.
- Allow Space or a canvas click to start, and held left mouse as an alternative
  to held Space. Keep upstream physics, collisions, scoring, colors and drawing.
- Draw a bobbing bird on the otherwise static main menu, reusing its drawing.
- Add startup assertions/markers and a bounded two-second native smoke mode
  when an argument is supplied. No assets or handwritten gameplay JS added.

The native smoke checks initialization and two seconds of the render loop.
The site browser check covers idle animation, starting, held/released input,
focus, scrolling and runtime errors. Full playthroughs, long-duration memory
behavior and non-Chrome browsers are not established by these bounded checks.
