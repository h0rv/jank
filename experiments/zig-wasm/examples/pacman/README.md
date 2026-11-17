# Pac-Man — native and browser jank

AI-assisted adaptation of the jank port in
[b12n-oss/raylib-pacman](https://github.com/b12n-oss/raylib-pacman), commit
`2094901ab2cf9fb5f05b02e7b04348ae1064694f`. Upstream's game is already jank;
the maze, buffered tile-centre movement, ghost personalities, scatter/chase,
power pellets, scoring, lives and levels are retained. The loop is factored
into `frame` for jank-build; native owns its loop, while browser RAF owns
pacing and the driver collects at empty-stack frame boundaries. No assets or
additional application C++/Zig/JavaScript game logic are needed.

Upstream's **EPL-2.0** text is retained in [LICENSE](LICENSE). Its
[NOTICE.md](NOTICE.md) retains attribution and the MIT notice for the original
game by **Michiel Borkent**, from babashka/ffi. Pac-Man belongs to Namco; this
example is unaffiliated. Raylib/raygui have separate zlib licenses retained by
the existing library build recipe. Keep this AI-assisted work in this fork,
not as an external contribution to upstream jank.

## Build and play

From `experiments/zig-wasm`:

```sh
./jank-build build examples/pacman  # native + wasm64, same source
./jank-build run native examples/pacman  # requires a desktop display in the container
./jank-build serve examples/pacman  # http://127.0.0.1:8765/; leave this running
```

Click the browser canvas to focus it. **Arrows or WASD** steer; **Enter**
restarts after game over. Native **Escape** closes the window. Native accepts
an optional positive number of game seconds as its first argument to bound a
run; without arguments it stays open. Browser runs indefinitely.

The build driver bootstraps its Ubuntu 24.04 `jank-host-build` container and
local SDKs. No Zig source or Zig installation is needed for this example.
Web output uses the existing Emscripten memory64 / WebGL2 (GLES3) raylib
recipe and private flatten/spill transform, not WASI or WasmGC. Use a browser
supporting memory64 and Wasm exception handling (Chrome 156 used locally).
Outputs and build logs are ignored under `artifacts/` and `.tools/`.

## Bounded checks

`jank-build check` takes only a project, not `native`/`browser` targets, and
expects terminating programs. Its Node check cannot create a GLFW/WebGL
window, and its generic DOM browser check does not exercise interactive
frames. Use these interactive-example equivalents after building:

```sh
# Once, only in the disposable build container, for headless native rendering:
docker exec jank-host-build bash -c 'apt-get update && apt-get install -y xvfb xauth'
bash examples/pacman/check-native.sh

# Keep ./jank-build serve examples/pacman running in another terminal.
# Chrome must have remote debugging enabled (default CDP port here: 29229).
node examples/pacman/check-browser.mjs http://127.0.0.1:8765/ /home/ubuntu/pacman-shots
```

`CHROME_CDP` overrides the CDP URL. The Node script uses only built-ins and
leaves the browser tab and server running. It checks both success markers,
renders screenshots, locates Pac-Man's yellow shape in actual framebuffer
pixels, and verifies right/left arrows reverse his horizontal movement.
It also sends up/down and checks GL errors and JavaScript exceptions. The
shared startup rule assertions cover walls/door/bounds/tunnel, all four input
directions and unknown keys, movement/turns, eating normal/empty/already-eaten
dots, pellets, ghost scoring, lives/game over and mode/level transitions.

Verified locally: native AOT built and rendered for two game seconds under
Xvfb / Mesa llvmpipe; both shared-rule and loop-completion markers passed.
The same source built to wasm64 and rendered a 610×730 maze in Chrome 156 /
WebGL2. The CDP check passed both startup markers and measured rightward
movement x=318→409 and leftward movement x=415→326 in framebuffer pixels;
all four arrows were sent. Five screenshots are in `/home/ubuntu/pacman-shots/`.
No GL errors or JavaScript exceptions were observed. The console did print
`GC Warning: Heap grown by 43236 KiB while GC was disabled` at startup:
the existing driver disables GC during initialization and collects between
frames. This is not a claim about long-term memory use. The first browser
probe sampled a reversal too early; it now allows a tile-centre turn before
measuring directional movement.

These checks are bounded, not a full playthrough, long-duration GC proof,
audio test or guarantee for other browsers/platforms. No Node graphics
execution or public site deployment is claimed.
