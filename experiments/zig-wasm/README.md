# jank, Zig and Wasm research

This directory preserves a measured experiment from 2026-11-16. It is AI-assisted research in a personal fork. It is not an upstream contribution or a claim that jank supports Wasm.

Read the complete handoff prompt at [`../../ZIG_WASM_PROMPT.md`](../../ZIG_WASM_PROMPT.md).

## Starting point

The branch starts at PR #1107 head `43ffa8d0a6bce1c17c552c6d46f4d6486dc304ed`. The PR separates a host compiler from a target static runtime and begins moving compiler configuration into JSON. The upstream PR remains authoritative for its current status.

The experiment uses an installed jank compiler for host code generation and a prebuilt native runtime. It does not build the fork's compiler or runtime. Submodule updates and compiler builds are separate steps.

## Results

| Test | Observed result |
| --- | --- |
| Native jank calls a Zig static archive through JIT and AOT execution. | Passed. |
| Zig compiles and links the generated application's C++. | Passed against the prebuilt jank runtime. |
| The same small C++ caller and Zig implementation run as wasm32 and wasm64. | Both passed in Node, without imported runtime functions. |
| C++ vector allocation/destruction runs on wasm32-WASI. | Passed through 10,000 calls. Exceptions and RTTI were disabled in this particular test. |
| Zig provides wasm64-WASI libc. | Failed with the tested Zig version. |
| An isolated jank-style tagged pointer survives encoding and decoding on wasm64. | Passed, without a collector. |
| The actual generated jank module compiles to wasm64. | Passed with Emscripten and Wasm exceptions enabled. Object file only. |
| The same module compiles to wasm32-WASI. | Failed on pointer width, platform guards and C++ threading dependencies. |
| Newer Boehm collects on wasm64 with an explicit registered root. | Smoke passed through 32 forced collections. |
| Newer Boehm discovers local roots with Asyncify. | Current smoke passes, but earlier variants lost live objects. Unresolved. |
| Binaryen pointer spilling works in the collector test. | Failed during linking. The collector suite correctly exits 1. |

The native Zig C++ build still uses the installed jank package's matching libc++, libunwind and LLVM 23 compiler runtime. It does not rebuild all dependencies with Zig. The generated launcher's extraction also invokes the installed jank compiler before the final Zig compilation.

No full jank Wasm runtime or target core library has been linked or executed. No jank tagged-reference GC test has passed. These distinctions must remain visible in future reports.

## Environment

The original tests used macOS arm64, Zig 0.17.1, Node 26.13.1, and an installed jank 0.1-alpha package. Its binary identifier was:

```text
arm64-apple-darwin27.2.0-f06292e476b8a74409cf7453b101e43fe5745607b6dcd2369d587d44f605e509
```

The GC experiment pins Emscripten 7.0.0 and Boehm commit `91f30f37b0457566e9823b8360da59f1798f65fc`. The SDK installer revision is pinned in its script. The SDK download and generated caches occupied about 1.9 GiB locally. They are excluded from git.

## Run the checks

Run these commands from this directory. Put the pinned Zig version, Node and a compatible jank on PATH. `mise exec -- bash ...` can supply the pinned Zig version.

```sh
bash scripts/check-jank.sh
bash scripts/check-jank-zig-cpp.sh
bash scripts/check-cpp-zig-wasm.sh
bash scripts/check-cpp-stdlib-wasm.sh
bash scripts/check-wasm-compat.sh
```

The native generated-C++ script is specific to the tested Homebrew package layout. Set `JANK_RUNTIME_DIR` if the package lives elsewhere. The LLVM 23 runtime paths in that script must also match the installed package. These are research scripts, not portable production build commands.

The header probe downloads exact pinned source files. It verifies expected compiler rejections. A synthetic Unix macro isolates the wasm64 pointer checks; it does not port the platform.

Bootstrap the separate collector experiment locally:

```sh
BOOTSTRAP=1 bash scripts/check-gc-wasm.sh all
```

That command downloads an official prebuilt SDK and source archives. It does not build LLVM from source or install system packages. Its expected current exit status is 1 because the spill test fails. Do not change the test to hide this failure.

After SDK bootstrap and native C++ source generation:

```sh
bash scripts/check-jank-wasm-object.sh
```

Read [`wasm-probe/GC.md`](wasm-probe/GC.md) before interpreting the collector results. Raw pointer roots and jank's tagged references are not the same test.

The isolated representation check is:

```sh
zig c++ -target wasm64-freestanding -std=c++20 -O2 -nostdlib \
  -Wl,--no-entry -Wl,--export=nanbox_round_trip \
  wasm-probe/nanbox.cpp -o artifacts/wasm-probe/nanbox64.wasm
node wasm-probe/nanbox.mjs
```

## Files

`native.zig` contains the implementation and three unit tests. It exports widening arithmetic and a borrowed-buffer function with explicit status values. The jank caller currently tests scalar arguments and a 64-bit result. A jank-side borrowed-buffer test remains to be added.

`build.zig` builds static and shared Zig libraries. `jank/src/spike/core.jank` is the Clojure caller. `scripts/` contains the reproduction commands. `wasm-probe/` contains isolated C++ callers, target-header probes and the collector test.

## Repository policy

The upstream `CONTRIBUTING.md` states that external contributions, including code and copy, must be exclusively human-created. These AI-assisted files are for research in this fork. Do not submit them upstream as human-created work or remove this provenance to bypass that policy.

No upstream issue, discussion, pull request or maintainer comment has been created for this experiment.
