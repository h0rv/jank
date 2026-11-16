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

### Linux

The three jank-dependent checks also passed on Linux x86_64 in an Ubuntu 24.04
container, using the local Zig 0.17.1 and Node 26.13.1 downloads. The PPA's
`dists/jammy/main/binary-amd64/Packages.gz` returned HTTP 404. Its noble package
requires newer glibc/libstdc++ than the Ubuntu 22.04 host, so it was unpacked
locally rather than installed on the host:

* Package: `https://ppa.jank-lang.org/pool/main/j/jank/jank_0.1-noble_amd64.deb`
* SHA-256: `95c564ef43c6dc096b6c35a8f0a7c2c1a4391158e523d536fc0d636853a13edf`
* `print-binary-version`: `x86_64-unknown-linux-gnu-cf627abb22b776c8ebbb6caee09f4f22fe25a16e33827b2ccc2eb155085e5e68`

With the package already extracted at `.tools/jank` using `dpkg-deb -x`, the
following reproduces the container setup and checks from this directory. The
existing local Emscripten 7.0.0 SDK from the GC bootstrap is reused. Package
installation occurs only inside the disposable container.

```sh
docker run --rm -v "$PWD/../..:/home/ubuntu/repos/jank" \
  -w /home/ubuntu/repos/jank/experiments/zig-wasm ubuntu:24.04 bash -c '
  mkdir -p artifacts/logs
  apt-get update > artifacts/logs/linux-container-setup.log 2>&1 &&
  DEBIAN_FRONTEND=noninteractive apt-get install -y gcc g++-14 libxml2 \
    libzstd1 zlib1g libbz2-1.0 libboost-dev curl git xz-utils file \
    ca-certificates python3 >> artifacts/logs/linux-container-setup.log 2>&1 || exit $?
  export PATH="$PWD/.tools/node-v26.13.1-linux-x64/bin:$PATH"
  export ZIG="$PWD/.tools/zig-x86_64-linux-0.17.1/zig"
  export ZIG_GLOBAL_CACHE_DIR="$PWD/.zig-cache/global" TMPDIR="$PWD/artifacts"
  export JANK="$PWD/.tools/jank/usr/local/bin/jank"
  export JANK_RUNTIME_DIR="$PWD/.tools/jank/usr/local/lib/jank/0.1"
  failed=0
  for name in check-jank check-jank-zig-cpp check-jank-wasm-object; do
    bash "scripts/$name.sh" > "artifacts/logs/linux-$name.log" 2>&1
    rc=$?
    echo "$rc" > "artifacts/logs/linux-$name.exit"
    [ "$rc" -eq 0 ] || failed=1
  done
  exit "$failed"
'
```

All three returned 0. `check-jank.sh` executed the scalar/wide-result assertions
through JIT and an AOT executable. `check-jank-zig-cpp.sh` compiled and linked
the generated application with Zig and executed it outside the source directory;
on Linux it uses GCC 14 headers and libstdc++/libgcc matching this package,
not Zig's libc++. The macOS library selection is unchanged.
`check-jank-wasm-object.sh` compiled the actual generated module to a wasm64
object with Emscripten and Wasm exceptions; it did not link or execute it.
These AI-assisted reproduction results do not establish a full jank Wasm runtime
or collector correctness for jank's tagged references.

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

`native.zig` contains the implementation and three unit tests. It exports widening arithmetic and a borrowed-buffer function with explicit status values. The jank caller tests scalar arguments, a 64-bit result, and the borrowed-buffer cases below.

### Borrowed-buffer FFI

`spike_sum_i32` borrows an aligned array of at least `len` signed 32-bit values
and a writable signed 64-bit output slot for the duration of the call. The caller
owns both, keeps them alive during the call, and frees them afterward. Zig does
not mutate the input or retain either pointer. Null input is permitted only at
zero length; a null output is always an error. Status 0 writes the sum (zero for
empty input); status 1 rejects invalid null pointers without changing a valid
output slot. Status 2 reports signed 64-bit overflow without changing output.

The AI-assisted jank test allocates a `std::vector<std::int32_t>` with `cpp/new`,
resizes it to four elements, fills it through `cpp/aget` and `cpp/=`, and passes
`.data()` plus a `cpp/new`-allocated `std::int64_t` output slot. A `finally` block
uses `cpp/delete` for both allocations, including the vector destructor that
releases its element storage. No handwritten C++ function implements the test
or the Zig operation; `cpp/raw` only includes headers and declares the C ABI.

On the Ubuntu 24.04 container and jank package above, `check-jank.sh` returned 0
with both scalar and `jank -> Zig: borrowed-buffer checks passed` lines in **each
of JIT and AOT execution**. `check-jank-zig-cpp.sh` also returned 0 with both
lines after Zig compilation/linking and native execution. Assertions cover:

* `[10 -3 20 15]` returning status 0 and sum 42 twice on the same buffer;
  all four input elements remain readable and unchanged.
* Refilling that same buffer with `[1 2 3 4]`, summing it twice to 10, and
  checking all elements again before caller cleanup.
* Null and non-null input with length zero, both returning 0 and writing zero.
* Null input with length one, returning 1 and preserving output sentinel 99;
  null input/output with length zero, returning 1.

These executions check the listed value and reuse behaviors, not general
memory safety. No-retention is also supported by inspection of the Zig function,
which stores no pointers beyond the call; the smoke alone cannot prove it.
Status 2 is untested: overflowing i64 with i32 elements requires roughly
`2^32` elements (about 16 GiB), not a practical smoke allocation.

A separate ignored `(assert false "deliberate assertion failure probe")` module
verified that assertions execute in JIT and AOT. JIT returned 1; AOT printed
`assertion failed` **but returned 0** with this installed jank. Both native
scripts therefore require the final scalar and buffer success markers from
the executable rather than trusting its exit code alone. Probe logs remain in
`artifacts/logs/buffer-assertion-*.log`.

One interop limitation encountered was
`(cpp/new (std.vector std.int32_t) (cpp/std.size_t. 4))`: the generated C++ used
`std::vector<int>{ v3, }` and Zig rejected it with
`non-constant-expression cannot be narrowed from type 'std::size_t' (aka 'unsigned long') to 'value_type' (aka 'int') in initializer list`.
Default construction followed by `.resize()` expresses the desired allocation
through supported jank interop without adding a C++ implementation.

`build.zig` builds static and shared Zig libraries. `jank/src/spike/core.jank` is the Clojure caller. `scripts/` contains the reproduction commands. `wasm-probe/` contains isolated C++ callers, target-header probes and the collector test.

## Repository policy

The upstream `CONTRIBUTING.md` states that external contributions, including code and copy, must be exclusively human-created. These AI-assisted files are for research in this fork. Do not submit them upstream as human-created work or remove this provenance to bypass that policy.

No upstream issue, discussion, pull request or maintainer comment has been created for this experiment.
