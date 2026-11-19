# Using Zig with jank

AI-assisted research in this fork, not a supported general Wasm toolchain.
Zig is an optional library language/toolchain here; it does **not** enable
jank's Wasm build. See the [experimental runtime limits](README.md#one-command-native--wasm).

## Adding a Zig library through jank-build

The worked example is this directory's spike. Its actual
[`jank-build.json`](jank-build.json) selects a Zig root alongside jank sources:

```json
{
  "name": "spike",
  "main": "spike.core",
  "jank": "jank/src",
  "zig": "native.zig",
  "expect": [
    "jank -> Zig: scalar and wide result checks passed",
    "jank -> Zig: borrowed-buffer checks passed"
  ],
  "wasm_check": "spike-continuous"
}
```

From `experiments/jank-wasm`, run `./jank-build check` to build and check native,
Node and browser outputs. Pass another project directory as the final argument.
For a new project, choose its own `name`, entry namespace and expected lines;
omit `wasm_check` for the ordinary single-run check. Omit `zig` entirely for
pure jank, as in [`examples/hello-cljc`](examples/hello-cljc/jank-build.json).
Host prerequisites and output locations are in the
[one-command instructions](README.md#one-command-native--wasm).

### Export and call C-compatible functions

[`native.zig`](native.zig) exports a widening addition using the C calling
convention; the result is widened **before** adding:

```zig
export fn spike_add(a: i32, b: i32) i64 {
    return @as(i64, a) + @as(i64, b);
}
```

The jank side, [`jank/src/spike/core.jank`](jank/src/spike/core.jank), declares
the symbol rather than implementing it in C++:

```clojure
(cpp/raw "extern \"C\" long long spike_add(int, int);")
```

Its `-main` calls it with explicit boundary types:

```clojure
(cpp/spike_add (cpp/int. 20) (cpp/int. 22))
```

The same file declares `spike_sum_i32` as
`extern "C" int spike_sum_i32(const std::int32_t*, std::size_t, std::int64_t*);`.
Its `check-buffer` allocates a `std::vector<std::int32_t>` and an output slot
with `cpp/new`, passes `.data()` and a length, and deletes both in `finally`.
Zig borrows these aligned buffers only during the call: it neither frees nor
retains them. The caller must keep the allocations valid and supply the real
length; the pointer/length ABI cannot verify allocation size.

Status 0 writes the sum; status 1 rejects invalid null pointers, preserving a
valid output slot; status 2 reports sum overflow. Empty input permits null and
writes zero. The [jank checks](jank/src/spike/core.jank) cover reuse, unchanged
inputs, empty input and null errors. The overflow status is **not exercised**
by those tests (see [ownership evidence](README.md#borrowed-buffer-ffi)).
Keep Zig slices, error unions, allocators and ownership behind this C ABI;
this integration does not import Zig types or C++ classes/templates into Zig.
Jank's existing C++ interop remains available on its side of the boundary.

### Build and link details

[`scripts/jank-build.py`](scripts/jank-build.py) generates a native library
recipe from [`scripts/project-build.zig`](scripts/project-build.zig), unless
the project provides `build.zig` (the spike has [one](build.zig)). Install both
static/shared libraries named after `name`. The generated template sets
`lib.bundle_compiler_rt = true;`: custom recipes do not inherit this setting
and must account for Zig compiler-runtime symbols when required. Native source
generation loads the library; final linking includes its static archive.
With `zig` present, the driver also uses `zig c++` for generated native C++, but
selects the container's GCC 14 headers and libstdc++ to match the jank runtime,
not Zig's bundled C++ standard library (`build_native`).

For Wasm, the **same configured Zig source** is compiled directly with
`zig build-obj -target wasm64-freestanding -O ReleaseSafe`. The object is linked
by Emscripten's `em++` alongside the jank objects/runtime (`build_wasm`). A custom
`build.zig` is not a Wasm build recipe: its extra dependencies or options are
not automatically forwarded to that direct object compilation. The isolated
freestanding kernel needs no Emscripten sysroot; **jank's Wasm runtime does**.

Use exact success lines as well as exit status: the
[recorded assertion probe](README.md#borrowed-buffer-ffi) found AOT assertion
failure could still exit 0. The driver's `expect` checks guard against that.
The experimental static-root/spill path and GC/exception-storage limitations
still apply; adding Zig does not fix them.

## Does Zig add anything over a plain C/C++ toolchain?

**Some toolchain convenience, not a new jank capability demonstrated here.**
The following small probes used pinned Zig **0.17.1** on Linux x86_64. Reproduce
with `bash scripts/zig-toolchain-probe.sh` after the documented local Zig/Node
bootstrap; `file` and `readelf` are also required. The script clears external
SDK/sysroot environment settings, logs commands/results to
`artifacts/logs/zig-toolchain-probe.log`, and keeps outputs under `artifacts/`.

| Claim | Evidence | Verdict |
| --- | --- | --- |
| One Zig kernel can target native and freestanding Wasm without an external SDK/sysroot. | [Probe](scripts/zig-toolchain-probe.sh): native ELF object and all 3 native tests passed; [isolated C++ caller](scripts/check-cpp-zig-wasm.sh) linked and ran wasm32 **and wasm64** in Node, with no imports asserted by [the harness](wasm-probe/cpp-zig.mjs). | Useful bundled cross-target tooling for small libraries, not proof of a jank runtime port or something Clang cannot do. |
| `zig c++` can target an older glibc without supplying a separate sysroot. | Probe builds a vector/printf C++ program with `-target x86_64-linux-gnu.2.28`; it prints `glibc-2.28 C++ sum: 42` on this host. `readelf --version-info` reports only `GLIBC_2.2.5`. | Promising packaging convenience for this tiny program; **not executed on glibc 2.28** or a different architecture. |
| This makes jank binaries portable to older Linux distributions. | [`build_native`](scripts/jank-build.py) still links the existing jank runtime and container GCC 14 libraries; [README](README.md#one-command-native--wasm) documents the Ubuntu-compatible library requirement. | **Untested.** Would need consistently targeted runtime/dependencies and execution on the oldest supported host, not just a flag on the final link. |
| Zig supplies checked behavior across the FFI boundary. | [`native.zig`](native.zig) uses widening arithmetic, explicit `@addWithOverflow` and status/null checks; its normal/empty/error tests passed. The borrowed input length remains trusted. | Useful explicit API design, also implementable in C/C++. No native/Wasm ReleaseSafe trap-versus-C-UB comparison was run; no general safety advantage established. |
| Zig enables or simplifies jank's Wasm runtime. | [`build_wasm` and `prerequisites`](scripts/jank-build.py) make Zig conditional; [`hello-cljc`](examples/hello-cljc/jank-build.json) has no Zig library. Emscripten compiles/links jank's C++ either way. | Not required. No GC, exception-rooting or runtime portability benefit demonstrated. |
| Adding Zig is free. | The [driver](scripts/jank-build.py) downloads/checks an extra 0.x-version SDK pin; the [template](scripts/project-build.zig) bundles compiler runtime; the spike exports a C ABI, not a direct Zig/C++ type bridge. | Extra toolchain, version pin, compiler-support/linking and boundary maintenance. These probes establish no speed or size win. |

Use Zig when you want to write a Zig library or value its bundled targeting
tools. For a pure-jank application, the existing Clang/Emscripten path is enough;
there is no evidence here to replace jank's C++ toolchain wholesale.
