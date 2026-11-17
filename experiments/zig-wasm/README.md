# jank, Zig and Wasm research

This directory preserves a measured experiment from 2026-11-16. It is AI-assisted research in a personal fork. It is not an upstream contribution or a claim that jank supports Wasm.

Read the complete handoff prompt at [`../../ZIG_WASM_PROMPT.md`](../../ZIG_WASM_PROMPT.md).

## Starting point

The branch starts at PR #1107 head `43ffa8d0a6bce1c17c552c6d46f4d6486dc304ed`. The PR separates a host compiler from a target static runtime and begins moving compiler configuration into JSON. The upstream PR remains authoritative for its current status.

The original baseline uses an installed jank compiler for host code generation and a prebuilt native runtime. The separate Linux host-build reproduction below builds this fork's compiler and native static runtime. The later wasm64 runtime-archive attempt builds a target archive and links the spike, but startup fails before its checks execute.

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
| Tagged-reference lifetime cases against the real jank runtime archive. | Native passes all seven; no automatic wasm64 strategy passes all. Explicit test-only shadow roots retain test locals but not runtime-internal lifetimes. |
| Binaryen pointer spilling works in the collector test. | Failed during linking. The collector suite correctly exits 1. |
| Fork-built wasm64 static runtime archive, including target core modules. | Built with an explicit collector backport and unsupported-capability gates; see the runtime-archive section. |
| Generated spike launcher/module plus Zig link against that wasm64 archive. | Linked with Emscripten. Node reaches a jank startup error; neither spike success marker is printed. |
| Fork-built wasm32 Emscripten runtime archive and generated spike. | Configure and Zig object succeeded; runtime/core and spike C++ fail on 64-bit pointer assumptions. No archive, link or Node execution. |
| Is the `reader_opts` startup error wasm64-specific? | Startup diagnostics trace wasm64's failure to missing runtime C++ static roots; wasm32 cannot yet reach startup for comparison. |
| Tagged jank map retention across wasm64 collections. | An explicitly registered static root passes; the default unregistered root is lost. This is a diagnostic control, not a runtime rooting solution. |

The native Zig C++ build still uses the installed jank package's matching libc++, libunwind and LLVM 23 compiler runtime. It does not rebuild all dependencies with Zig. The generated launcher's extraction also invokes the installed jank compiler before the final Zig compilation.

The later wasm64 spike links the target runtime/core libraries and begins execution, but does not complete successfully. Startup diagnostics establish a missing-static-root defect. The real-runtime lifetime matrix below passes natively but finds no automatic wasm64 strategy that passes all cases; explicit test-only shadow slots do not cover runtime-internal locals. A linked application is not evidence of correct general root discovery or a supported general-purpose Wasm runtime.

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

### Linux fork compiler and native cross-mode runtime

This AI-assisted follow-up built the fork based on
`fc2270a6bd1551b3562d864d8006299e2190b44d` in Ubuntu 24.04 Docker on Linux
x86_64. No host packages or submodule pins were changed. Build products,
caches and logs remain under ignored experiment directories.

The build guide says LLVM 22, while `cmake/llvm.cmake` accepts 22 through 23
(less than 24). `bin/build-clang` pins jank's LLVM fork at
`e280c5056ed110a11411413da2b76da226f3113b`, branch `jank-snapshot/llvm23`.
That source build was unnecessary for these native checks: apt.llvm.org's noble
LLVM/Clang **23.1.6** worked, including CppInterOp and the tests. The package
version was
`1:23.1.6~++20261116013850+5b10d2d74929-1~exp1~20261116133903.98`,
from `https://apt.llvm.org/noble/ llvm-toolchain-noble-23 main`, with RTTI
enabled. This is a rolling repository: retain this version when reproducing,
and do not silently substitute another snapshot if unavailable. GCC/libstdc++
headers were 14.2.0, CMake 3.28.3 and Ninja 1.11.1.

From this experiment directory, the container/toolchain setup is:

```sh
mkdir -p artifacts/logs
docker run -d --name jank-host-build \
  -v "$PWD/../..:/home/ubuntu/repos/jank" \
  -w /home/ubuntu/repos/jank/experiments/zig-wasm ubuntu:24.04 tail -f /dev/null
docker exec jank-host-build bash -c '
  set -euo pipefail
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl gnupg \
    git build-essential g++-14 cmake ninja-build pkg-config python3 file xz-utils \
    libssl-dev libdouble-conversion-dev libffi-dev libbz2-dev libboost-all-dev \
    zlib1g-dev libzstd-dev libxml2-dev libedit-dev
  curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key | \
    gpg --dearmor -o /usr/share/keyrings/llvm.gpg
  echo "deb [signed-by=/usr/share/keyrings/llvm.gpg] https://apt.llvm.org/noble/ llvm-toolchain-noble-23 main" \
    > /etc/apt/sources.list.d/llvm.list
  apt-get update
  version="1:23.1.6~++20261116013850+5b10d2d74929-1~exp1~20261116133903.98"
  apt-get install -y "clang-23=$version" "llvm-23-dev=$version" \
    "libclang-23-dev=$version" "libclang-cpp23-dev=$version" \
    "clang-tools-23=$version" "lld-23=$version"
' > artifacts/logs/host-container-setup.log 2>&1
# Only if the pinned submodules are missing:
docker exec --user "$(id -u):$(id -g)" jank-host-build \
  git -C /home/ubuntu/repos/jank submodule update --init --recursive
for step in host test spike target install target-install target-spike; do
  docker exec --user "$(id -u):$(id -g)" jank-host-build \
    bash scripts/build-host-linux.sh "$step" || break
done
```

The helper uses six jobs, Release, `/usr/lib/llvm-23`, `jank_test=ON`,
`artifacts/build-host`, and `artifacts/build-target`. `LLVM_PREFIX` and `JOBS`
can be overridden. It creates `artifacts/host-resources` links to source,
headers and host build libraries because a development build outside the usual
`compiler+runtime/build` otherwise cannot find `clojure.core`. It exports
`LANG=C.UTF-8 LC_ALL=C.UTF-8`: the original POSIX locale caused
`lex/unterminated-string` on the Unicode ellipsis in `jank/nrepl/server/util.jank`.
No compiler source changes were needed. Reusing earlier root-owned outputs also
required restoring ownership of `.zig-cache`, `zig-out`, `jank/target`, and
the prior spike logs/output to the bind-mount user. Fresh runs should use the
same unprivileged UID throughout.

Observed results (`artifacts/logs/host-*.log` and adjacent `.result` files):

| Step | Exit | Evidence / scope |
| --- | ---: | --- |
| Host configure | 0 | LLVM/Clang 23.1.6 accepted; final configure 1 s |
| Host build | 0 | Built `jank`, `jank-phase-1`, runtime archives and `jank-test`; final incremental build 90 s |
| Tests | 0 | 128/128 doctest cases, 2024/2024 assertions; 868 jank files, 9 skips, 0 failures; 11 s |
| Spike | 0 | Fork `jank` JIT execution, AOT compilation/link and execution outside source tree; scalar and buffer markers twice; 2 s |
| Native cross configure | 0 | `jank_cross_compile=ON`, built host **phase-1** compiler, same native target; final configure 1 s |
| Native cross runtime build | 0 | `jank_standalone_static_lib_phase_2` produced `libjank-static-runtime.a`; 63 s after initial failed attempt |
| Host install | 0 | Headers, archives and `lib/target_config.json` under `.tools/host-install`; config byte-identical; 1 s |
| Cross-mode install | 0 | No-op: no `.tools/target-install` created; 0 s |
| Cross-runtime spike | 0 | Fork-generated C++ compiled/linked by Zig 0.17.1 against the explicit cross-mode archive, then executed; both markers once; 6 s |

Times are per invocation, not a clean-build benchmark. The earlier resource-path
failure and a 145 s locale-failing retry preceded the final 90 s host build.
The first test invocation used the wrong working directory (`test/jank` missing);
the helper now runs tests from `compiler+runtime`. The fork binary identifier was
`x86_64-pc-linux-gnu-edaf8df469178412f23536c50ca4e8ba799380f7da4ade5aeeafe6208f6bb177`.

**Cross-mode limitations:** first configuring with
`HOST_COMPILER="$PWD/artifacts/build-host/jank"` succeeded, but its build failed:
`clang++: error: no such file or directory: '.../build-target/core-libs/_cache/0/clojure/core.cpp'`.
Phase 2 registers managed core load functions, and the loader takes that path
instead of generating core C++; switching to the fork-built `jank-phase-1`
produced the missing files without modifying CMake or compiler sources.
The helper defaults to phase 1 for `jank_host_compiler`; `HOST_COMPILER` can
override it. The original diagnostic is retained in
`host-target-build-phase-2-failure.log`.

Both generated configs record `triple: x86_64-pc-linux-gnu` and
`clang_bin: /usr/lib/llvm-23/bin/clang++`. Flags include native GCC 14 and LLVM
23 include paths, `-femulated-tls`, `-fPIC`, and source/build resource paths.
`aot_flags` also contains the erroneous but nonfatal
`-Ljank_lib_link_dirs_prop-NOTFOUND` from an unset CMake target property.
Code inspection shows the JSON triple is **not applied** as `--target`;
`clang_bin` supplies include/rpath directories but **does not select the invoked
compiler** (`invoke_clang` calls `find_clang`, using the host configured path).
`jit_flags`/`aot_flags` are appended to AOT compiler arguments. Runtime library
search remains relative to the host process/resources, not the target config.
Install rules are explicitly disabled in cross mode; the ordinary host install
places JSON at `lib/target_config.json`, not beside the runtime archive.
The `target-spike` step therefore reuses installed host headers and explicitly
passes the target archive via the existing Zig C++ check, rather than claiming
automatic target-config-based runtime selection.

This demonstrates native host/target separation and native execution only.
It does not test another architecture, the installed compiler's relocatability,
a complete Wasm runtime, or general collector/FFI memory safety.

### Initial wasm64 target-runtime blocker probe (historical)

This section records `devin/1794872204-wasm64-target-runtime`, including that
revision's helper options and failures. The following runtime-archive section
supersedes its build status and describes the current helper.

This AI-assisted attempt starts from the Linux host-build branch at
`5e5fa76e48a41485cf1be6b8f93413baad570a33`. It reuses that Ubuntu 24.04
container, native `artifacts/build-host/jank-phase-1`, and the local Emscripten
7.0.0 SDK documented in `wasm-probe/GC.md`. It does **not** produce a complete
target runtime archive, linked application, or Wasm execution result.

From the experiment directory in the existing container setup:

```sh
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh deps
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh configure
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh build
```

The helper uses `emcmake`, its genuine Emscripten toolchain and compiler wrappers,
`-sMEMORY64=1 -fwasm-exceptions` for C/C++ and executable linking, Release,
`jank_cross_compile=ON`, `jank_emulated_tls=OFF`, `enable_threads=OFF`, six jobs,
and `--target jank_standalone_static_lib_phase_2 -- -k 0`. There is no `-pthread`,
Unix/Linux macro injection, fake platform implementation or no-op unwinder.
`EMSDK` and `JOBS` can override the SDK directory and parallelism. Logs/results
are `artifacts/logs/wasm64-*`; builds are in `artifacts/build-wasm64`.

**Configure:** the unmodified project stopped with `Unsupported OS: Emscripten`.
Two small CMake changes allow useful diagnostics without claiming platform
support: select wasm-ld's supported `--whole-archive`/`--no-whole-archive`
switches, and do not re-inject Emscripten's implicit include list as explicit
standard includes. That list puts C headers before libc++ and caused widespread
`<cstddef> ... didn't find libc++'s <stddef.h>` errors. The compiler itself
provides the correct implicit order. Other platforms retain their existing path.

Cpptrace's automatic configuration then stopped with
`No unwinding back-end seems to be supported, stack tracing will not work`.
For **diagnostic collection only**, the helper explicitly selects its real
`CPPTRACE_UNWIND_WITH_UNWIND=ON` implementation, despite the failed availability
probe. This permits generation of build rules and preserves compile-time errors;
it does not supply a working unwinder. `CPPTRACE_UNWIND_WITH_NOTHING` is not used.
PCH is disabled using CMake's standard option so a single failed PCH cannot hide
all runtime translation units.

Required ZLIB/Boost discovery initially failed. `deps` builds Emscripten's
memory64 zlib 1.3.2 port and installs its Boost 1.83.0 headers. Header-only links
under `.tools/wasm64-headers` avoid explicitly adding the entire sysroot C-header
directory ahead of libc++. These are target SDK dependencies, not host archives.

**Host leakage:** the project still discovers native LLVM/Clang 23.1.6 at
`/usr/lib/llvm-23` and appends its include directory globally. To satisfy the
native LLVM package's exported `zstd::libzstd_shared` dependency, configuration
uses host zstd's package config with `CMAKE_FIND_PACKAGE_PREFER_CONFIG=ON` and
package root searching set to BOTH. This imports a native library; it must not
be used in a real Wasm link. Libdwarf's generated compile command demonstrably
contains `-isystem /usr/include` and reads host libc headers (see table).
The generated JSON also retains `-L/usr/lib/llvm-23/lib`, its `c++`/`unwind`
subdirectories, host resource links, and `-Ljank_lib_link_dirs_prop-NOTFOUND`.
Its Clang major macro says 23 while the target SDK resource directory is Clang
24. Its recorded triple is **wasm32-unknown-emscripten**, because the triple query
does not pass memory64 flags. Actual compilation does pass memory64: predefined
macros show `__wasm64__`, `__SIZEOF_POINTER__=8`, and Wasm exception handling.
Emscripten itself defines `__unix__`; the experiment does not add it.

**Compile:** final configure returned 0 in 4 s, and the final keep-going build
returned 1 in 83 s. Host core generation succeeded (16 generated C++ files),
and all 16 core modules compiled into Wasm objects. All 11 selected Folly
sources compiled and `libfolly.a` was archived. Immer-using runtime files,
terminal code, the static-runtime implementation, zip and nanobench also
compiled. These are compile/archive observations, not runtime correctness tests.

The table counts **113 failed object compilation edges by first diagnostic**
in the final build, not 113 independent root causes. Secondary errors and
masked failures are not added to the counts. Full commands and diagnostics are
retained in `wasm64-build.log`; the enumerated outputs/diagnostics are also in
the ignored `wasm64-failures.json` analysis output.

| File or dependency | Count | First diagnostic | Category |
| --- | ---: | --- | --- |
| `src/cpp/jank/util/environment.cpp:112`, `process_path()` | 1 | `static assertion failed: Unsupported platform` | Missing process/filesystem platform implementation |
| `include/cpp/jank/runtime/core.hpp:186` via core/module/sequence/object sources and `clojure/string_native.cpp` | 10 | `no type named 'delay_ref' in namespace 'jank::runtime::obj'` | Missing direct declaration exposed without PCH; not demonstrated Wasm-specific |
| `src/cpp/jank/aot/target_config.cpp` | 1 | `no member named 'format' in namespace 'jank::util'` | Missing direct include exposed without PCH; not demonstrated Wasm-specific |
| Pinned bdwgc C sources (`alloc.c`, `allchblk.c`, etc.) | 20 | `64-bit WebAssembly is not yet supported` | Collector target configuration |
| Cpptrace binary/platform/unwind/symbol sources | 29 | `"Unexpected platform"` | Stack-trace platform layer; masks real unwind API compilation |
| Cpptrace's fetched libdwarf sources | 52 | `'bits/libc-header-start.h' file not found` from `/usr/include/{stdint,stdlib,string}.h` | Host-header contamination |

By category: platform/stack traces **30**, non-PCH include/declaration issues
**11**, collector **20**, host-header contamination **52**. No Folly/Immer
threading-header failure was observed with this SDK; that is not evidence their
synchronization works at runtime. The project still injects `-DGC_THREADS` into
236 compile-database commands despite `enable_threads=OFF` and zero `-pthread`
commands. That inconsistent runtime/collector contract is unresolved; no
thread-capable runtime or collector is claimed. Terminal code compiled, but
TTY/filesystem behavior was not executed. The reachable `process_path()`
implementation has no Emscripten case and fails explicitly rather than returning
a fake native path.

**Collector backport assessment:** upstream
`3f4e077edb2496bfd14e625f3a440f38caac458a` changes one header (6 additions,
5 deletions), replacing the wasm64 rejection/32-bit word-size definition with
conditional 64/32-bit word size. `git apply --check` succeeds against the pinned
`327ef1f8c80a611b2f8b915850c8b2fd38e6595e`. This is a small mechanical backport
candidate, but it was **not applied** and the pin remains unchanged. It does not
resolve the separate `GC_THREADS` restriction or expose Wasm local roots; the
root-discovery limitations in `wasm-probe/GC.md` remain.

**Link/execution:** neither final archive merging nor application linking was
reached; `libjank-static-runtime.a` does not exist in this build. No application
or collector was executed. Native regression configure/build remained successful
(`ninja: no work to do.`), and the native tests still reported 128/128 cases,
2024/2024 assertions, 868 jank files with 9 skips and 0 failures.

### wasm64 runtime archive and spike link attempt

This AI-assisted follow-up starts from `16e7e1b832e6d47b200cc42294859eaba32a3eea`.
It preserves native defaults and the bdwgc submodule pin. Changes were committed
separately: missing includes, collector integration/threading, executable-path
semantics, stack-trace gating, regression coverage, and future cancellation.

From this experiment directory, with the same Ubuntu 24.04 container and local
Emscripten 7.0.0, Zig 0.17.1 and Node 26.13.1 tools:

```sh
# Refresh native binaries/PCH after header changes; the helper exports C.UTF-8.
docker exec --user 1000:1000 jank-host-build bash scripts/build-host-linux.sh host
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh deps
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh configure
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh build
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh spike
docker exec --user 1000:1000 jank-host-build bash scripts/build-host-linux.sh test
```

`build` still uses `-k 0`. `spike` generates the real launcher and module using
the fork's native compiler, reuses the target core module's compile flags from
`compile_commands.json` (not the host-link flags in the JSON target config),
and compiles `native.zig` with `zig build-obj -target wasm64-freestanding
-O ReleaseSafe`. It then links with:

```sh
em++ -sMEMORY64=1 -fwasm-exceptions -O2 \
  artifacts/wasm64-spike/main.o artifacts/wasm64-spike/core.o \
  artifacts/wasm64-spike/zig.o artifacts/build-wasm64/libjank-static-runtime.a \
  -Wl,--error-limit=0 -o artifacts/wasm64-spike/spike.js
.tools/node-v26.13.1-linux-x64/bin/node artifacts/wasm64-spike/spike.js
```

No unresolved-symbol suppression, fake symbols, platform macro injection, or
handwritten implementation of the Zig calls is used. The output is an Emscripten
JS launcher plus Wasm module, not a freestanding/import-free module. Outputs and
logs stay under ignored `artifacts/wasm64-spike` and `artifacts/logs/wasm64-*`.

**Source changes:** `runtime/core.hpp` includes the actual delay definition and
`target_config.cpp` includes `util/fmt.hpp`. The collector had no existing patch
mechanism: `bdwgc.cmake` previously built the pinned submodule directly. On
Emscripten only, it now copies that source into `build-wasm64/bdwgc-source` at
configure time and applies `cmake/dependency/bdwgc-wasm64.patch` there, with Git
repository discovery bounded so ignored build paths are not silently skipped.
Native builds still use the untouched submodule directly. The patch reproduces
Ali Kamarainen's upstream `3f4e077edb2496bfd14e625f3a440f38caac458a`: one header,
6 additions/5 deletions, conditional `CPP_WORDSZ=64` for `__wasm64__` (32 otherwise),
plus its architecture-list comment. It changes neither root discovery nor the
collector algorithm, and the pin stays at `327ef1f8c80a611b2f8b915850c8b2fd38e6595e`.

`GC_THREADS` is now conditional on the collector's `enable_threads` option.
Non-thread builds skip GC thread registration and explicitly throw
`Futures require a thread-enabled runtime` for future creation/cancellation/
cancellation queries. They do not report fake future completion. Native threaded
implementations remain unchanged. The first real spike link exposed
`undefined symbol: pthread_tryjoin_np`; guarding cancellation queries removed
that Unix threading extension from the non-thread target.

Emscripten does not configure/build cpptrace or libdwarf. Trace collection,
resolution and stored trace fields are gated out; exception maps have an empty
trace, and exception/panic printers say `Stack traces are unsupported on
Emscripten.` Ordinary typed exception handling remains. Native calls still use
cpptrace's implementation via an alias. Target zstd 1.5.7 remains necessary for
compressed runtime resources, so it is fetched independently with a verified
SHA-256 and threading disabled, rather than being obtained through cpptrace.

`process_path()` throws `Executable paths are unavailable on Emscripten`.
Consequently `process_dir()` also fails clearly: compiler/resource-discovery
callers cannot infer a native executable directory in the Wasm virtual
filesystem. No fake path or current-directory fallback is returned.

**Configure/compile/archive:** configure returned 0 in 5 s; the final incremental
keep-going build returned 0 in 40 s. All 16 target core modules and the runtime
and dependency objects compiled, and the PR #1107 merger produced the
23,890,548-byte `libjank-static-runtime.a`. This is archive creation, not an
executable link. Final failures grouped against the initial table:

| File/dependency | Failed object edges now | Outcome/category |
| --- | ---: | --- |
| `runtime/core.hpp` / `aot/target_config.cpp` | 0 | Direct include fixes remove the 11 non-PCH errors |
| Pinned bdwgc | 0 | Credited word-size patch applied to private build copy; non-thread compilation |
| Cpptrace/libdwarf | 0 | Not built on Emscripten; stack traces explicitly unsupported |
| `util/environment.cpp`, `process_path()` | 0 | Explicit unsupported-executable-path exception |
| Folly/Immer/terminal/zip/zstd/static runtime/core modules | 0 | Compiled; not general runtime-correctness claims |

The current 349-command database has **0** `GC_THREADS`, **0** `-pthread`, **0**
cpptrace source commands, and **0** libdwarf source commands. Host discovery is
not solved globally: LLVM/Clang 23 metadata, the incorrect recorded wasm32
triple, and LLVM include/library paths remain. Another **72 unbuilt compiler/
CppInterOp commands** still contain explicit `/usr/include`; none of their
objects existed in the target build. The selected static-runtime archive build
did not hit those commands. The application link uses only the target SDK
library directories, not host LLVM/zstd archives.

**Link/run:** the final link returned 0 in 3 s and produced a 3,275,690-byte Wasm
module. There are **zero remaining missing-symbol diagnostics**. Node returned
0 but printed:

```text
The `reader_opts` argument must be a map, not a `persistent_list`.
Stack traces are unsupported on Emscripten.
```

Neither scalar nor borrowed-buffer success marker appeared. `spike` therefore
returns **1**, not success: `jank_init_static` currently returns 0 after caught
exceptions, so process status alone is insufficient. The diagnostic originates
in the map check in `context::read_string` (`runtime/context.cpp`); the reason
the wrong object type reaches it was **unverified at this milestone**. The
following startup investigation supplies additional evidence; the original
diagnostic alone did not establish its cause.

| Phase | Remaining blocker | Count/category |
| --- | --- | --- |
| Archive compilation/merging | None observed | 0 failed edges |
| Initial spike link | `pthread_tryjoin_np` | 1 missing native-thread-extension symbol; resolved |
| Final spike link | None observed | 0 missing symbols |
| Spike execution | Reader options observed as a list instead of a map | 1 observed startup error; root cause unresolved |

Before linking the spike, the helper also links/runs `wasm-probe/runtime-smoke.cpp`
against the archive. Normal/empty callbacks and standard, jank-object, jank-error
and unknown exceptions dispatch correctly; process-path and all three guarded
future APIs throw their explicit errors. Node output:

```text
runtime smoke exception
Stack traces are unsupported on Emscripten.
wasm64 runtime: exception dispatch and unsupported capabilities passed
```

The final native build returned 0 (78 s incremental), and `jank-test` returned
0 (13 s): **129/129** cases, **2029/2029** assertions, **868** jank files,
**9** skips and **0** failures. The added dispatch regression supplies five
assertions. These results do not validate general filesystem/TTY behavior,
Wasm GC root visibility, tagged-reference GC safety, or successful spike
execution. The earlier collector-suite limitations remain unresolved.

### Applying target configuration to AOT and installing the target SDK

This AI-assisted follow-up uses `devin/1794875064-apply-target-config`, based on
the wasm64 runtime-archive branch above. It addresses configuration/driver/SDK
selection, not the unresolved Wasm startup error. The older target-config and
cross-install limitations above describe earlier revisions.

**Source changes:** `target_json.cmake` accepts `jank_target_triple`, otherwise
queries the configured compiler with tokenized `CMAKE_CXX_FLAGS`, and fails
configuration on an unsuccessful or empty query. The unset link-directory
property is no longer serialized as `-L...-NOTFOUND`. In cross mode only, flag
serialization filters the discovered host LLVM/Clang include/library/install
roots and the configured host resource directory. Other target/source paths
are preserved; this is not a runtime-only CMake redesign.

External AOT object compilation and executable linking now use the JSON
`clang_bin` and `--target=<triple>`. A nonempty missing compiler path is an error,
not a request to fall back to the host. Empty compiler paths retain host
discovery. Cross configs (a nonempty triple different from the host default)
omit host executable/resource include/library paths and rpaths, use SDK-relative
`include`/`lib` directories, and resolve the forced prelude through target
include paths. Native paths retain their previous behavior. Host JIT/PCH and
analysis must stay native: for a cross config they use the default host config
and `find_clang()`, not the target compiler or target header flags.

Emscripten **7.0.0** was probed directly:

```text
em++ -sMEMORY64=1 -print-target-triple
wasm64-unknown-emscripten
```

`--target=wasm64-unknown-emscripten -sMEMORY64=1` is accepted too: driver `-###`
output used that `-cc1 -triple`, and a compiled probe had `Arch: wasm64` and
`AddressSize: 64bit`. Neither an em++ exception nor a hard-coded script triple
override was necessary. The experiment helper's existing memory64 flags suffice.

Cross installation now stages only headers, `libjank-static-runtime.a`, and
`target_config.json` under `lib/jank/0.1/`. It does not install the dummy phase-2
library, a host executable, or a dynamic runtime. The bundled target zstd's
independent install rules are excluded from this SDK installation; its objects
remain merged into the runtime. Native install rules are unchanged. Default
JSON loading still tries beside the executable first (development builds), then
`../lib/target_config.json` (the existing native install location).

**Reproduction:** bootstrap the documented container, pinned LLVM 23.1.6 and
Emscripten 7.0.0 SDK first. No system packages were installed on the host, and
submodule pins were unchanged. From this experiment directory:

```sh
python3 scripts/check-target-config.py
docker exec --user 1000:1000 jank-host-build bash scripts/build-host-linux.sh host
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh deps
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh configure
python3 scripts/check-target-config.py --generated artifacts/build-wasm64/target_config.json
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh build
docker exec --user 1000:1000 jank-host-build cmake --install artifacts/build-wasm64 \
  --prefix /home/ubuntu/repos/jank/experiments/zig-wasm/.tools/wasm64-install
docker exec --user 1000:1000 jank-host-build python3 scripts/check-target-aot.py
docker exec --user 1000:1000 jank-host-build bash scripts/build-host-linux.sh test
docker exec --user 1000:1000 jank-host-build bash scripts/build-host-linux.sh install
docker exec --user 1000:1000 jank-host-build .tools/host-install/bin/jank print-binary-version
```

The configure-only regression covers explicit/query/failed/empty triples,
absent/present link directories, cross filtering, and preservation of native
flags (7 tests). `--generated` prints the complete JSON and asserts the wasm64
triple, absence of `NOTFOUND`, `/usr/lib/llvm-*` and host-resource paths in both
flag fields. The AOT regression creates a tiny jank module, a recording em++
wrapper and a temporary config beside the staged config. It logs the **actual**
forwarded compiler command, checks target selection and host-path exclusion,
inspects the object with the SDK's `llvm-readobj`, exercises missing/failing
compilers and empty-path fallback, then links/runs a native default-config AOT
executable. Each attempt uses a fresh target directory.

**Configure/compile/archive/install results:**

| Check | Result and scope |
| --- | --- |
| Configure-only regression | 7 tests, OK, 0.141 s |
| wasm64 configure | Exit 0; 75 s initially including dependency setup, 3 s final cached configure |
| Generated JSON | `triple=wasm64-unknown-emscripten`, `clang_bin=.../upstream/emscripten/em++`; all path/sentinel assertions passed |
| Host build | Exit 0; 198 s successful retry, 75 s final incremental build after the prelude fix |
| Target archive | Exit 0; 229 build edges, 96 s initial archive build; 40 edges, 34 s final incremental refresh |
| Target SDK install | Exit 0; 2457 files, all under `lib/jank/0.1/`; archive 23,883,114 bytes |
| Cross AOT module | Exit 0 using the staged config's recording wrapper, `--target=wasm64-unknown-emscripten` and `-sMEMORY64=1`; no host LLVM/resource paths in recorded arguments |
| Target object inspection | `Format: WASM`, `Arch: wasm64`, `AddressSize: 64bit` |
| Staged-header-only compilation | Exit 0 after removing **all** source-tree `-I` arguments from the recorded command; object is wasm64 |
| Missing/failing compiler | Both exit 1 with the expected diagnostics; no host fallback |
| Empty compiler/triple | Native object compile exits 0 using host discovery |
| Native installed config discovery | Installed `jank print-binary-version` exits 0 without an explicit config or a JSON beside `bin/jank` |

Full generated JSON remains at `artifacts/build-wasm64/target_config.json` and
`.tools/wasm64-install/lib/jank/0.1/target_config.json`. Logs are
`artifacts/logs/{host-*,wasm64-*,target-config-aot.log}`. The full SDK file list
is `artifacts/logs/wasm64-installed-files.txt`; representative entries are:

```text
lib/jank/0.1/include/jank/prelude.hpp
lib/jank/0.1/lib/libjank-static-runtime.a
lib/jank/0.1/target_config.json
```

**Link/run results:** native default-config AOT links and executes, printing
`target config native AOT passed`. The final native suite reports:

```text
tested 868 jank files with 9 skips and 0 failures
[doctest] test cases:  129 |  129 passed | 0 failed | 0 skipped
[doctest] assertions: 2029 | 2029 passed | 0 failed |
[doctest] Status: SUCCESS!
```

This round did **not** link or execute a complete Wasm jank application, rerun
the Zig spike, or retest collector safety. The historical startup error remains
unresolved. The C++ changes compile in the host; target AOT object production is
verified, not successful Wasm application execution. Zig was not invoked or
upgraded; its experiment pin remains 0.17.1.

**Failures and remaining limitations:** the first host build caught an ambiguous
`immutable_string != std::string` comparison; explicit conversion fixed it.
The recording check then caught a host-resource prelude path despite clean
JSON; cross AOT now uses `-include jank/prelude.hpp`. The test harness initially
looked one directory too high for `llvm-readobj`; its path was corrected.
Reusing the cross output directory exposed a separate existing loader issue:
it tried to load the previously emitted Wasm object into the host and reported
`Failed to find symbol: 'jank_load_target_config_smoke'`. This round does not
redesign module caching/loading; use fresh target directories for these probes.
The cache directory's version prefix still names the host architecture.
Generated configs retain absolute checkout and target-SDK paths, so a fully
relocatable SDK is not claimed. macOS/Windows cross-host behavior is untested.

### wasm32 runtime archive and spike attempt

This section records the comparison before target-config application was merged.
Its target-config/path-leak limitations are historical; the runtime pointer-width
blockers below are not fixed by applying the target triple.

This AI-assisted comparison starts from PR #5 head `2ea3f2828`. **Whether the
`reader_opts` error is wasm64-specific remains undetermined:** wasm32 fails
before archive creation, not at startup. The wasm64 startup investigation below
traces its cached reader-options map changing type across collection to missing
runtime C++ static roots; it does not claim a complete rooting fix.
No runtime representation, target-config
implementation or collector source was changed to force it through.

The fresh VM had no experiment tools, builds or container. The documented
Ubuntu 24.04 container was recreated with the exact LLVM 23.1.6 package version
above, Emscripten 7.0.0, Zig 0.17.1 and Node 26.13.1. All downloaded SDKs,
builds and logs are under ignored experiment directories; no VM packages or
global tools were installed/replaced. The scripts export `C.UTF-8` and use
`jank-phase-1` for target core generation. The native Zig archive was prepared
with `build-host-linux.sh spike` (0, 109 s; both markers in JIT and AOT).

`build-wasm64-target.sh` now accepts `WASM_BITS=32` (default remains 64), selects
`artifacts/build-wasm32`, `artifacts/wasm32-spike`, `.tools/wasm32-headers` and
`artifacts/logs/wasm32-*`, omits `--wasm64` from embuilder, omits MEMORY64 from
all C/C++/link flags, and uses `zig build-obj -target wasm32-freestanding`.
The runtime-smoke success line now prints its compiled pointer width.

```sh
# First reproduce the wasm64 flow as above, including native host and Zig archive.
for step in deps configure build spike; do
  docker exec --user 1000:1000 -e WASM_BITS=32 jank-host-build \
    bash scripts/build-wasm64-target.sh "$step" || break
done
# Even after build fails, independently inspect spike generation/Zig/C++:
docker exec --user 1000:1000 -e WASM_BITS=32 jank-host-build \
  bash scripts/build-wasm64-target.sh spike
```

Results below are exit / elapsed seconds, per invocation, not benchmarks.
Source inspection is recorded in `wasm32-source-inspection.{log,result}`;
other phases use the helper's matching `.log`/`.result` files.

| Phase | Reproduced wasm64 baseline | wasm32 |
| --- | --- | --- |
| Source inspection | Existing 64-bit pointer/NaN-box representation | 0 / 0 s; `__wasm32__`, pointer size 4, Wasm exceptions; 349/349 commands omit MEMORY64 |
| Native host configure / build | 0 / 9 s; 0 / 205 s | Same host used |
| Target dependencies | 0 / 4 s | 0 / 2 s |
| Target configure | 0 / 67 s | Initially 1 / 51 s; metadata discovery fix: 0 / 4 s |
| Compile / archive | 0 / 84 s | 1 / 68 s; 143 failed object edges, no final archive |
| Spike host generation / Zig object | 0 / 1 s; 0 / 0 s | 0 / 1 s; 0 / 0 s |
| Spike C++ compile | 0 / 5 s | 1 / 3 s; same pointer-width errors |
| Runtime-smoke compile | Included in spike compile | Independent attempt: 1 / 2 s; same pointer-width errors |
| Runtime-smoke link / Node | 0 / 17 s; 0 / 0 s | Not reached |
| Spike link / Node | 0 / 4 s; 0 / 0 s | Not reached; no Node output |
| Correctness / marker gate | Spike helper 1: neither success marker | Not reached; neither marker, no startup comparison |

The first wasm32 configure rejected the native zstd package's 64-bit version
check and LLVM's imported `LLVMSupport` then lacked `zstd::libzstd_shared`.
For wasm32 only, the helper supplies `zstd_LIBRARY` and `zstd_INCLUDE_DIR` to
LLVM's module finder, the same host-metadata dependency already present in
the wasm64 configuration. This is not a target zstd implementation: the real
target zstd is still fetched/built separately. Host LLVM discovery/path leakage
remains unresolved; neither host zstd nor LLVM is supplied to the spike link.

All 143 failed object edges first report `jtl/primitive.hpp:42`:
`static assertion failed due to requirement 'sizeof(unsigned long long) == sizeof(void *)'`.
`uptr`/`usize` are fixed `unsigned long long`; line 43 asserts the same width.
Secondary errors include string-size narrowing and `runtime/oref.hpp` pointer
bit casts to/from `u64`/`f64`: libc++ rejects `sizeof(object *) == sizeof(double)`
because **4 == 8 is false**. Changing only the size aliases cannot fix the
NaN-box encoding, which stores 64-bit numeric/tag data in pointer-sized fields.
Removing assertions, truncating tags or injecting platform macros would not
preserve the same runtime semantics. A 32-bit representation port is outside
this comparison's minimal-build-fix scope. The existing collector patch already
selects `CPP_WORDSZ=32`; it is not the first failing edge. Its correctness and
the earlier collector-suite failures remain unresolved.

All 16 core C++ files were generated natively. Both the core and the actual
spike fail through their real runtime-header includes, so this is not merely
an unused-header probe. The generated launcher also hardcodes
`using jank_usize = unsigned long long` (`aot/processor.cpp::gen_entrypoint`);
its PCH-size declaration is not exercised by this static entrypoint. The spike
buffer declaration retains `std::size_t` rather than a baked numeric size.
No later generated-source ABI failures can be excluded before the headers
compile. Core-generation commands in `CMakeLists.txt` pass no `--target-config`;
the spike helper likewise uses native analysis then target compile-database
flags. `target_json.cmake` records `wasm32-unknown-emscripten`, but
`aot::build_compiler_args` does not apply that triple as a target or alter the
NaN-box representation. Merely changing the JSON triple cannot resolve this.

Exact wasm64 Node baseline output (spike process exit 0, helper exit 1):

```text
The `reader_opts` argument must be a map, not a `persistent_list`.
Stack traces are unsupported on Emscripten.
```

Exact wasm64 runtime-smoke output (exit 0):

```text
runtime smoke exception
Stack traces are unsupported on Emscripten.
wasm64 runtime: exception dispatch and unsupported capabilities passed
```

After parameterization and the width-aware smoke change, the wasm64 spike was
checked again: generation 0 / 2 s, Zig 0 / 0 s, C++ 0 / 6 s, smoke link
0 / 2 s and run 0 / 0 s, spike link 0 / 4 s and run 0 / 0 s. Both Node outputs
were identical to the baseline; the helper still exits 1 for missing markers.
The SDK warns that MEMORY64 is deprecated in favor of `-m64`; the documented
baseline was deliberately retained. Script syntax passed; invalid `WASM_BITS=16`
was rejected with exit 2. No runtime sources changed. Native `jank-test`
additionally returned 0 / 9 s: 129/129 cases, 2029/2029 assertions, 868 jank
files, 9 skips and 0 failures. No wasm32 runtime correctness is claimed.

### wasm64 startup investigation: GC root visibility

This AI-assisted investigation starts from `2ea3f2828e82dbc5cfe01bd51c16fcf8976291e6`.
**No production runtime fix is claimed or committed here.** The evidence exposes
a rooting design requirement, not a call-site argument swap. All temporary
runtime edits were removed. Diagnostic instrumentation is retained as
`wasm-probe/startup-context.patch`, applied only to an ignored copy compiled into
a separate diagnostic executable; the normal runtime archive is not modified.

#### Reachable failing path and direct observation

The generated main calls `jank_load_clojure_core()` before loading `spike.core`.
Generated `clojure.core` initialization reads source metadata through
`reset_meta(..., _jank_eval_str("{:jank/source ...}"))`. The static implementation
in `src/cpp/jank/codegen/api_static.cpp` calls `context::forcefully_read_string`,
which calls the **one-argument** `context::read_string(code)`. That overload
creates its own cached `persistent_array_map` containing `:eof`/`:eofthrow`, then
forwards it through the two-argument overload to the three-argument map check.
Neither generated main nor the generated metadata call passes reader options.

With only a conditional diagnostic at that cached map, the same startup error
was reproduced together with:

```text
STARTUP cached defaults: original-type=persistent_array_map current-type=persistent_list original-gc=3 current-gc=4 code={:jank/source {:module "clojure.core", :file "/home/ubuntu/repos/jank/compiler+r
The `reader_opts` argument must be a map, not a `persistent_list`.
Stack traces are unsupported on Emscripten.
```

Thus the target constructs a correctly typed map and later observes a different
type at the cached pointer after a collection. The exact allocation that reuses
that memory was not traced. Instrumentation/link layout changes can change the
symptom: the retained SAFE_HEAP diagnostic reports a `persistent_hash_map`
instead, followed by a `memcmp`/`module::is_core_module` segmentation fault.
The temporary exact-list observation remains in
`artifacts/logs/startup-cached-defaults.log`.

#### Rooting evidence and alternatives checked

The active collector's `gcconfig.h` defines **equal** `DATASTART` and `DATAEND`
under `WEBASSEMBLY`/`EMSCRIPTEN`, so automatic static-data registration has an
empty range. The runtime's `jank_init_base()` did not add its static roots.
This does **not** mean the generated modules register no roots: `cpp_processor.cpp`
emits `GC_add_roots` for lifted variables and constants, and both calls are
present in the generated `clojure.core` loader. Those generated ranges do not
provide rooting for handwritten runtime C++ statics such as the cached reader
options. The diagnosed gap is in runtime C++ static roots, not the absence of
all generated root registrations.
The uninstrumented release link map at `artifacts/wasm64-spike/startup.map`
places the cached reader-options slot at **0x1bc3b8**, outside the two generated
core ranges (constants **[0x1b2238, 0x1b55a4)** and variables
**[0x1b55a8, 0x1b5e98)**). These are observed addresses, not values to hard-code.
The target compile database also has zero `EMSCRIPTEN_ASYNCIFY`, `ASYNCIFY`, or
`spill-pointers` occurrences. In `os_dep.c`, the single-threaded extra-root hook
is zero unless `EMSCRIPTEN_ASYNCIFY` is enabled. The collector's own
`docs/platforms/README.emscripten` requires cooperation to expose Wasm locals;
native conservative stack assumptions are insufficient.

`startup-roots.cpp` exercises the real runtime allocator and a volatile static
slot holding a **tagged jank map reference**, not a raw-pointer replacement.
After an explicit collection it checks the collector mark bit, then allocates
32,768 further maps and checks the retained map's payload when marked. It does
not dereference an unmarked object. The registered control changes only
`GC_add_roots` for that slot; GC remains enabled in both cases:

| Same diagnostic source | Collections | Marked | Original payload retained | Exit |
| --- | ---: | ---: | ---: | ---: |
| Native, default roots | 10 | 1 | 1 | 0 |
| Native, registered slot | 10 | 1 | 1 | 0 |
| wasm64, default roots | 25 | 0 | 0 | 1 |
| wasm64, registered slot | 25 | 1 | 1 | 0 |

Both targets report sizes **88/80/16** for array map/list/object, alignment **8**
for each, object type offset **8**, and array-map data offset **72**. Both use
`POINTER_MASK=0x0000FFFFFFFFFFFF`. The registered tagged-reference control works
with that same mask; it disproves the hypothesis that these current addresses
or tags are inherently undecodable. It does not validate the entire wasm64
address space. For the failing reader-options path, construction/layout/type
selection all happen in target C++, and the initial type is correct. No
host-computed layout constant is needed by that call. Inspection found no
`sizeof`/`alignof`/`offsetof` emission in `cpp_processor.cpp`; this is not a
complete audit of every interop or code-generation path.

The root-retention failure is **proven**, and the cached map changing type
across collection directly links startup to that defect. A deterministic
argument-order/arity mismatch cannot explain a target-created cached map first
being correct and then changing type. As a further countercheck, the same
diagnostic binary reaches all spike assertions when automatic GC is disabled.
Disabling collection is **only a diagnostic**, never the proposed fix.

#### Same generated spike, native versus wasm64

`startup-trace` compiles the same generated launcher and `spike.core` C++ for
both targets, linked to their respective runtime archives and the same Zig
source. It renames only the launcher entry point to attach diagnostic controls;
it does not edit assertions or implement Zig functions in C++. The core-library
archives themselves are the separately generated native/target builds, not
byte-identical generated core-library code. Target links add `-g`,
`ASSERTIONS=2`, `SAFE_HEAP=1`, and `ALLOW_MEMORY_GROWTH=1`. All three Wasm controls
use the **same binary** and memory-growth setting:

| Run | Result | Raw exit |
| --- | --- | ---: |
| Native, GC enabled | Both success markers; 15 collections | 0 |
| wasm64, default GC | Cached map type changes; segmentation fault | 1 |
| wasm64, GC disabled diagnostically | Both success markers; GC disabled, collection counter 1 | 0 |
| wasm64, only static data registered (`__global_base` to `__data_end`) | Gets further, but traps with `RuntimeError: function signature mismatch` in `reduce` while loading `spike.core` | 1 |

The globals-only control is a check **against** calling static registration a
complete fix. It removes the observed cached-defaults failure but still fails
before spike checks. Missing Wasm-local roots are the leading explanation for
the remaining GC-sensitive corruption, **not a traced proof of which local is
lost**; the later function-signature trap has not been independently minimized.
A supported solution needs a complete globals/stack/Wasm-locals rooting strategy
and tagged-reference lifetime tests. Selectively pinning `default_reader_opts`,
disabling collection, or merely growing the heap would not supply that strategy.

The GC-disabled diagnostic prints:

```text
jank -> Zig: scalar and wide result checks passed
jank -> Zig: borrowed-buffer checks passed
startup diagnostic: exit=0 collections=1 gc-disabled=1
```

The unchanged scalar/buffer assertions run before these markers. A separate
`startup_assertion.jank` deliberately asserts false. Both native execution and
the GC-disabled Wasm diagnostic print `:cause "assertion failed"` with message
`startup diagnostic assertion` yet return **0**. This establishes that the
assertions are present in AOT but caught language failures do not propagate a
nonzero exit through `jank_init_static`. Marker/output checks remain necessary.

#### Commands and final status

Run from this experiment directory after the earlier build/spike generation:

```sh
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh startup-roots
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh startup-trace
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh build
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh spike
docker exec --user 1000:1000 jank-host-build bash scripts/build-host-linux.sh test
```

`startup-roots` returns 0 only when the documented retention matrix reproduces,
including the expected unregistered-Wasm failure. `startup-trace` records every
control and returns **1** because production-GC success markers remain missing;
it does not turn the GC-disabled result into a runtime pass. Logs are
`artifacts/logs/wasm64-startup-*`. The negative assertion module and diagnostic
controls are never linked into the normal spike.

The final uninstrumented archive build returned 0, spike link returned 0, and
Node again printed the original `reader_opts`/`persistent_list` error with raw
exit 0; the spike helper correctly returned **1**. Native `jank-test` returned
0 in 12 s: **129/129** cases, **2029/2029** assertions, **868** jank files,
**9** skips and **0** failures. No native/compiler/collector source behavior,
dependency pin, or normal spike assertion was changed.

### wasm64 tagged-reference collector lifetime matrix

This AI-assisted follow-up tests `wasm-probe/gc-roots.cpp` against the actual
`libjank-static-runtime.a`, not the standalone newer `gc.c` experiment. It calls
`jank_init_base()`, never `jank_init_static()` or a core-module loader. It makes
no startup fix and changes no runtime or collector source. The existing
`POINTER_MASK` and private wasm64 collector backport are preserved.

#### Commands and build variants

From this experiment directory, in the existing Ubuntu 24.04 container:

```sh
docker exec --user 1000:1000 jank-host-build bash scripts/build-host-linux.sh host
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh build
docker exec --user 1000:1000 jank-host-build bash scripts/build-wasm64-target.sh gc-roots
docker exec --user 1000:1000 jank-host-build bash scripts/build-host-linux.sh test
```

The incremental host/target refreshes returned 0. The matrix returned **1** in
25 s; native regression tests returned 0 in 9 s. Logs are
`artifacts/logs/wasm64-gc-roots-*.log`, including separate compile, link and
per-case execution logs. `artifacts/logs/wasm64-gc-roots.results` records every
mode/case outcome. Cases run in separate processes so an abort cannot hide the
remaining cases. The source also supports running all cases in one process;
the matrix deliberately does not use that layout. Success requires both the
case marker and `GC ROOTS: 1 passed, 0 failed`, plus exit 0.

Probe compilation ends in `-O2`; Wasm links use the spike's `-O2
-sMEMORY64=1 -fwasm-exceptions -Wl,--error-limit=0`, without SAFE_HEAP,
ASSERTIONS, exception suppression or unresolved-symbol suppression. Runtime
objects retain the normal archive build flags. Host flags come from the native
compile database, without its PCH, and link the native archive with
`-lz -ldl -pthread`. Wasm probe flags come from the target compile database.

The Asyncify variant copies the real merged archive to
`artifacts/build-wasm64-asyncify/libjank-static-runtime.a`, recompiles every
collector `gc.dir` object from the target compile database with the **sole
additional compiler flag** `-DEMSCRIPTEN_ASYNCIFY`, and replaces those members
with `llvm-ar r`. This is the definition added by bdwgc's
`enable_emscripten_asyncify` option. All other runtime/core members are unchanged.
The link adds that option's `-sASYNCIFY -sASYNCIFY_STACK_SIZE=128000`.
The spill variant adds `-sBINARYEN_EXTRA_PASSES=--spill-pointers` to the normal
archive link. Neither variant replaces the collector with the newer GC probe.

#### Cases, detector and controls

All held test values are `object_ref`; tracked objects must have pointer tag
`0xFFFA`. Integers are `make_box(i64)` values starting at `0x100000000`, not
inline i32 values. Fixtures contain 128 alternating heap integers and persistent
strings in a runtime-built persistent vector. `locals` keeps one local ref
through 32 churn/forced-collection rounds and checks every element each round;
`nested` keeps independent fixtures across 32 recursive frames and checks on
unwind; `temporary` passes a newly produced fixture directly to a collecting
callee. The two global cases differ only in registering the static tagged slot.
With static-data registration, even the explicitly unregistered slot is covered
by `__global_base..__data_end`, as intended.

Each fixture object and every payload has a disappearing link stored as a
hidden pointer in rooted `GC_MALLOC_ATOMIC` memory. Untagging for registration
is confined to a noinline helper. The detector does not retain raw payload
pointers. Cleared links are checked before payload access; automatic GC is
disabled only during fixture construction/detector registration and payload
verification, never during the tested churn/collection intervals. No language
objects are retained in the detector array. `reclaim-control` drops the only
ordinary reference and requires its hidden-only object's link to clear, with
up to 32 collection rounds and stack clearing to reduce stale native roots.
Every passing case also requires `GC_get_gc_no()` to advance.

`runtime-internal` builds an 8,192-entry persistent hash map using runtime
`assoc`, heap-boxed keys/values and free-space divisor 64. A collection-event
hook counts collections **only while `assoc` executes**, excluding key/value
setup and test verification. All payloads are weakly watched and final contents
are checked only if none were lost. Native observed **33** such collections;
default Wasm **26**, static-roots and shadow **13** each. Thus merely collecting
between runtime calls cannot satisfy this case. This tests handwritten runtime
allocation paths without injecting a collector call into runtime source.

The explicit shadow control adds `GC_ROOTS_SHADOW`: a registered tagged slot
array holds test refs with scoped clearing, including map/key/value inputs.
It does **not** root handwritten runtime C++ locals, internal intermediate
objects or nodes. It is not an automatic strategy or a runtime fix.

#### Compile, link, execution and correctness results

P = marker and clean exit; F = failing case marker and exit 1; A = execution
aborts after markers (not a pass); L = link failed, case not executed.

| Mode | locals | nested | temporary | runtime-internal | registered-global | unregistered-global | reclaim-control |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Native | P | P | P | P | P | P | P |
| wasm64 default | F | F | F | F | P | F | P |
| wasm64 static-roots | F | F | F | F | P | P | P |
| wasm64 static-roots + Asyncify | A | A | A | A | A | A | A |
| wasm64 static-roots + spill | L | L | L | L | L | L | L |
| wasm64 static-roots + test shadow slots | P | P | P | F | P | P | P |

All probe compilations and the Asyncify collector compilation/archive succeeded.
All links except spill succeeded. All runnable non-Asyncify negative controls
passed. Asyncify printed passing global/reclaim markers but still aborted with
exit 1; its other four case markers were FAIL. It is not counted as passing any
case. The exact SDK warning and execution diagnostics were:

```text
em++: warning: ASYNCIFY=1 is not compatible with -fwasm-exceptions. Parts of the program that mix ASYNCIFY and exceptions will not compile. [-Wemcc]
Aborted(TypeError: Cannot convert null to a BigInt)
RuntimeError: unreachable
```

This Emscripten 7.0.0 link happened to succeed despite the incompatibility
warning; execution did not complete cleanly. No exception-disabled substitute
is presented as a real-runtime pass, and the exact cause of the BigInt abort
has not been isolated. Spill failed in Binaryen before execution:

```text
Fatal: getStackSpace: failed to find the stack pointer
```

Representative release failures (the normal log format, not a caught startup
exception) were:

```text
CASE locals: FAIL collections=3 internal-collections=0
CASE nested: FAIL collections=1 internal-collections=0
CASE temporary: FAIL collections=3 internal-collections=0
CASE runtime-internal: FAIL collections=26 internal-collections=26
CASE unregistered-global: FAIL collections=3 internal-collections=0
GC ROOTS: 0 passed, 1 failed
```

The shadow runtime-internal case likewise reports
`CASE runtime-internal: FAIL collections=13 internal-collections=13`.
The matrix never treats expected Wasm failures as success: exit 0 requires the
host and at least one **automatic** Wasm mode to pass every case. No such mode
passed. Native regression output was **129/129** doctest cases,
**2031/2031** assertions, **870** jank files, **9** skips, **0** failures.

#### Limits

This finite optimized-source layout cannot prove general conservative scanning:
compiler spills, accidental copies, detector instrumentation and changed link
layout may preserve a value an uninstrumented application would lose. Noinline
construction/registration/collection helpers, NaN-tag checks, no raw root
copies, weak slots and the reclaim control reduce those false positives; they
cannot eliminate them. Test-held collection construction is GC-disabled, so
these cases do not validate allocation-time safety during fixture construction.
The runtime-internal case separately exercises collection during actual runtime
code, but does not identify the exact lost intermediate or prove every runtime
allocation path safe. Internal vector/map nodes and string backing storage are
not separately weakly watched; runtime operations themselves are not a memory
safety sandbox. Passing payload checks are bounded observations, not a proof
of absence of all dangling internal storage.

No core startup, generated modules, JIT, browser, concurrency, arbitrary Wasm
address ranges, or complete spike correctness is tested here. No runtime source
change or supported production rooting strategy is claimed.

### Main merge and target-config regression checks

The AI-assisted merge of main into `devin/1794875064-apply-target-config`
preserves both historical sections above, the width-parameterized Wasm helper,
and the target-config changes. The only textual conflict was in this README.
`check-target-config.py` now tests both widths' host-path filtering and an
unflagged wasm32 triple query. Its generated-config check accepts `WASM_BITS=32`
(default 64), matching the build helper:

```sh
WASM_BITS=32 python3 scripts/check-target-config.py \
  --generated artifacts/build-wasm32/target_config.json
```

Post-merge Ubuntu 24.04 results: host configure/build exited 0 in 1/128 s;
native `jank-test` exited 0 in 12 s:

```text
tested 870 jank files with 9 skips and 0 failures
[doctest] test cases:  129 |  129 passed | 0 failed | 0 skipped
[doctest] assertions: 2031 | 2031 passed | 0 failed |
[doctest] Status: SUCCESS!
```

Configure-only regression: **8 tests, OK**. Wasm64 configure exited 0 in 3 s;
wasm32 dependencies/configure exited 0 in 2/59 s. Both generated JSON checks
passed triple, `NOTFOUND`, host LLVM and host-resource assertions. Wasm32 records
`wasm32-unknown-emscripten` without MEMORY64; wasm64 records
`wasm64-unknown-emscripten` with MEMORY64. Neither needs a triple override.

The wasm64 runtime archive rebuilt successfully (58 s), and SDK installation
returned 0 before running `check-target-aot.py`. Its recording compiler verified
the configured `em++`, `--target=wasm64-unknown-emscripten` and no host
LLVM/resource paths; inspection reported `Format: WASM`, `Arch: wasm64`,
`AddressSize: 64bit`. Missing/failing compiler negative controls exited 1 as
expected; native default AOT compile/run and empty compiler/triple fallback
exited 0. Full commands/results are in ignored
`artifacts/logs/merge-target-aot.log` and `merge-wasm64-install.log`.

No wasm32 archive/AOT/link/run was attempted in this merge check: successful
configuration does not fix the previously documented runtime pointer-width
blockers. No wasm64 application link/run or GC-root matrix was repeated here;
the runtime correctness limitations above remain.

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
