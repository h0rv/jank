# Private raylib/raygui browser probe (AI-assisted)

From `experiments/jank-wasm`, after the jank-build bootstrap supplies the local
Emscripten 7.0.0 SDK and `jank-host-build` container:

```sh
bash scripts/build-raylib-probe.sh wasm64
node scripts/check-raylib-browser.mjs
bash scripts/build-raylib-probe.sh native
```

`build-raylib.sh native|wasm64` builds just the libraries. Outputs are cached
under ignored `artifacts/raylib/<target>/{include,lib}`. Build logs and the
Chrome screenshot are under `artifacts/logs/raylib/`. Native prerequisites are
installed only inside the existing container, not on the host. Downloads are
SHA256-checked. Changed build script or patches invalidate the library cache;
remove a target's `stamp` to force rebuilding after a toolchain change.

Raylib is the pristine official **6.0** archive plus the checked-in patch.
Raygui is the exact **v5.0** header and implementation translation unit bundled
in Clojars `org.jank-lang.commons/raygui-sys:2026.09-5`, not an inferred Git
revision. That jar declares raylib-sys `2026.09-1`; this probe deliberately uses
raylib 6.0. Both upstream zlib licenses are retained beside the output libraries
and in extracted sources. No Tetris source or assets are included here.

The one-line patch converts the `EM_JS` canvas output pointer to a Number for
Emscripten's JS string helper. Memory64 passes C pointers as BigInt. This is a
bounded low-address JS interoperability adaptation, not a >2^53 address claim
or an audit of clipboard, fullscreen, software-renderer and other platform APIs.

The web build selects raylib's `PLATFORM_WEB` GLFW backend, so the final link
needs `-sUSE_GLFW=3`. It uses GLES3 with `-sMAX_WEBGL_VERSION=2` to match the
WebGL2 context, plus `-sMEMORY64=1 -fwasm-exceptions -sEXIT_RUNTIME=0` and memory
growth. A preliminary GLES2 build linked to WebGL2 rendered pixels but reported
GL error 1281; the matched GLES3 build passes the probe's GL error checks.
`emscripten_set_main_loop(frame, 0, 0)` schedules frames and lets main return;
there is no Asyncify or simulated infinite-loop exception.

The Node-built-in-only check launches a loopback-only HTTP server and headless
Chrome/SwiftShader, verifies a drawn pixel, sends a Space key through CDP,
requires the changed pixel and C console marker, clicks `GuiButton`, rejects
browser exceptions and saves `probe.png`. It stops its server/browser afterward.
This is a finite C integration check, not jank execution or general wasm64
raylib platform coverage. The native probe is linked, not automatically run.
Nothing is publicly served or deployed.
