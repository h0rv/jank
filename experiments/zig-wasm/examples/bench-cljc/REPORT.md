# Shared ClojureScript / jank benchmark

AI-assisted fork research, measured 2026-11-17. This is a bounded experiment,
not a claim of general Wasm support. All kernels live in
[`src/bench/core.cljc`](src/bench/core.cljc); reader conditionals only select
clock implementation and the ClojureScript CLI entry hook. `timing.cpp` adds
timing boundaries and GC policy, not alternate kernel implementations.

## Reproduce

From the repository root on Linux x86_64 with Docker, Python 3, curl, tar, and
Node 24 on `PATH`:

```sh
python3 -B experiments/zig-wasm/examples/bench-cljc/measure.py
python3 -B experiments/zig-wasm/examples/bench-cljc/measure_test.py
```

The driver calls jank-build's prerequisite bootstrap (the documented Ubuntu
24.04 `jank-host-build` container flow), source generation and native build
helpers. For Wasm it uses the same runtime, compiler flags, memory64/EH link,
static-root registration and private spill transform, with an instrumented
launcher. A clean bootstrap is substantial; allow approximately 17 minutes.
See [the experiment README](../../README.md) for prerequisites and limitations.

ClojureScript uses the official release jar, `:optimizations :advanced`,
`:target :nodejs`, and `:main bench.core`. The driver downloads and verifies
the jar and a local JRE 21; system Java 17 cannot run this Closure compiler
(class file version 65). Nothing is installed globally. All SDKs, generated
sources, compiler caches, logs and outputs stay under ignored `.tools/` and
`artifacts/` in the experiment. Zig is not used by this pure Clojure project;
the experiment's pin remains **0.17.1**.

Outputs: `experiments/zig-wasm/artifacts/bench-cljc/results.json` (metadata,
statuses, exact checksums, all ten samples), `results.md` (tables), and
`*-run.log` / build logs. Redirect driver stdout to an ignored file if desired.
`--targets cljs-js native wasm64-spill` selects a subset; `--skip-build` reuses
existing artifacts and must only be used with unchanged source/toolchains.

**The complete measured run exits 1**, intentionally: unsafe no-spill runs out
of memory. Successful targets remain recorded; failed targets are not silently
discarded. An exit-0 jank executable is not a correctness pass. The parser
requires all six checksum lines, ten finite nonnegative samples each, matching
medians, exactly one `BENCH PASS`, valid timing boundaries, and the expected
GC-policy marker. Empty output, missing markers, bad checksums, invalid timing,
nonzero exit and allocation errors are rejected by tests.

## Environment and workload

| Item | Measured value |
| --- | --- |
| CPU / available processors | Intel(R) Xeon(R) Processor / 8 |
| Node (all JS/Wasm runs, host) | v24.22.2 |
| ClojureScript | 1.12.145, latest stable listed at clojurescript.org/news when selected |
| Java | Eclipse Temurin JRE 21.0.9+10, local download |
| jank source/toolchain base commit | `81e343dac94f9c5749a1fe5f1dc314d323e8896a` |
| Emscripten | 7.0.0 |
| Native execution | Ubuntu 24.04 container, jank-build Release runtime |
| Wasm application compilation | Emscripten `-O2`, memory64, Wasm exceptions, 4 MiB stack, growable memory |
| ClojureScript jar SHA-256 | `fe33197a3e0e8ca9d2c52c3b4413f216ca309a0d67b4cdffe919c236c7f19f0a` |
| Shared source SHA-256 | `6ecbd23bf085ba0e3a2cc4991c6747b5ef4d529abf1029985f617919be76b350` |
| Private Binaryen patch SHA-256 | `e226384854712c6d94cbda84685d4fe427c9a1c2d159aae5dcb76dd3fd60bf92` |

The recorded jank commit predates this benchmark-only commit; no runtime code
was changed. `measure.py` records the checkout commit on each future run.
Node 24 from the host is deliberately used rather than jank-build's internal
Node download, so ClojureScript and Wasm use the same engine version.

Kernels: recursive fib(27); persistent vector construction and reduction over
100,000 elements; hash-map construction and 100,000 lookups; lazy
`range` → `map inc` → `filter even?` → reduction over 100,000 elements;
`str` plus comma join of 1,000 items; permutation sort of 5,000 values with a
position-weighted checksum. Sizes are identical across targets. Pilot runs
at 10,000 strings/sort values exceeded the requested native timing range;
the final sizes put native warm medians at approximately 1–65 ms.

Vector/map/lazy/sort accumulators and expected values use doubles on **all**
targets; these integer-valued sums are exactly representable below 2^53.
An integer-only pilot failed loudly (`expected=4999950000 actual=704982704`)
on jank; a mixed integer/double expected-value pilot also failed its equality
check. Neither pilot's timings are used below. No runtime arithmetic changes
were made to conceal these differences.

## Results

One fresh process per target; each kernel has one first run followed by ten
warm samples. Median is the mean of the sorted fifth and sixth samples.
Numbers are milliseconds, rounded only for display.

| Target | Compile | Link/transform | Execute | Correctness | Process wall ms | Init → entry ms |
| --- | --- | --- | --- | --- | ---: | ---: |
| cljs-js | PASS | N/A (Closure advanced) | exit 0 | PASS | 845.742 | 7.128 |
| native | PASS | PASS | exit 0 | PASS | 2088.088 | 67.994 |
| wasm64-spill | PASS | PASS | exit 0 | PASS | 8563.894 | 3144.755 |
| wasm64-unsafe | PASS | PASS | exit 0 | FAIL | 2042.343 | — |

| Target | Pre-runtime startup ms | First entry including kernels ms |
| --- | ---: | ---: |
| cljs-js | 20.169 | 803.059 |
| native | N/A | 2083.184 |
| wasm64-spill | 67.387 | 8329.767 |
| wasm64-unsafe | N/A | N/A |

Process wall includes Node/Wasm loading, module/runtime initialization, all 66
kernel executions, printing and teardown. Native wall is measured around the
child executable **inside** Docker, excluding `docker exec` startup. JS/Wasm
wall is measured around host Node. Pre-runtime startup is Node's uptime before
requiring the compiled JS, or at Emscripten `preRun`; these are different
boundaries, not directly equivalent loader measurements. Native pre-runtime
startup is not instrumented. `Init → entry` spans the launcher/module init
boundary to the first line of the shared `-main`; `First entry including
kernels` spans that init boundary through return from the complete benchmark.
These columns overlap and must not be added together. Failed-target timing
boundaries are withheld rather than treated as complete runs.

| Kernel | Target | Checksum | First ms | Warm median ms (10) |
| --- | --- | ---: | ---: | ---: |
| fib27 | cljs-js | 196418 | 12.579 | 7.012 |
| vector100k | cljs-js | 4999950000 | 15.753 | 9.644 |
| map100k | cljs-js | 5000050000 | 72.173 | 41.408 |
| lazy100k | cljs-js | 2500050000 | 11.081 | 3.020 |
| strings1k | cljs-js | 7889 | 0.767 | 0.094 |
| sort5k | cljs-js | 41666665000 | 4.250 | 1.193 |
| fib27 | native | 196418 | 1.310 | 1.273 |
| vector100k | native | 4999950000 | 22.144 | 16.366 |
| map100k | native | 5000050000 | 64.112 | 50.838 |
| lazy100k | native | 2500050000 | 77.148 | 44.401 |
| strings1k | native | 7889 | 1.453 | 1.495 |
| sort5k | native | 41666665000 | 51.751 | 64.429 |
| fib27 | wasm64-spill | 196418 | 100.591 | 93.078 |
| vector100k | wasm64-spill | 4999950000 | 60.192 | 48.913 |
| map100k | wasm64-spill | 5000050000 | 132.303 | 107.133 |
| lazy100k | wasm64-spill | 2500050000 | 184.808 | 130.146 |
| strings1k | wasm64-spill | 7889 | 8.396 | 6.413 |
| sort5k | wasm64-spill | 41666665000 | 97.345 | 60.643 |

| Kernel | spill / cljs-js (warm) | spill / native (warm) |
| --- | ---: | ---: |
| fib27 | 13.275× | 73.106× |
| vector100k | 5.072× | 2.989× |
| map100k | 2.587× | 2.107× |
| lazy100k | 43.100× | 2.931× |
| strings1k | 67.924× | 4.289× |
| sort5k | 50.825× | 0.941× |

### Unsafe no-spill failure

The untransformed Wasm module is run with **GC disabled before runtime entry**;
it is explicitly unsafe, not a supported alternate runtime. It completes the
fib/vector/map records, then fails before the lazy result, without `BENCH PASS`:

```text
GC Warning: Out of Memory! Heap size: 1983 MiB. Returning NULL!
std::bad_alloc
Stack traces are unsupported on Emscripten.
```

It still returns 0. The driver reports correctness FAIL, retains the complete
run log, and exits 1 overall. No partial unsafe timings or ratios are promoted
to benchmark results. The heap limit/GC policy were not changed to force a pass.

## Interpretation and limits

The experimental spill build is slower than optimized ClojureScript for every
measured kernel (2.6×–67.9×), and slower than native on five of six (2.1×–73.1×).
Sort is approximately equal here (0.94× native); this single process with ten
samples does not establish a speed advantage. There are no confidence intervals,
isolated-core runs or multi-process repetitions. The very short ClojureScript
string sample is especially sensitive to timer/JIT effects. Runtime algorithms,
boxing and compiler optimization differ despite identical Clojure source;
these ratios cannot be attributed solely to Wasm instruction overhead.

Startup matters: spill `Init → entry` alone is about 3.14 s versus 68 ms native
and 7 ms ClojureScript, separate from the timed kernels. Whole-process times
are not per-kernel steady-state throughput.

The spill/native runs have GC enabled (`gc-disabled=0`); the unsafe variant has
`gc-disabled=1`. The spill run emits collector warnings about repeated large
allocations, which are retained in its log and may affect timing. Both Wasm
variants use a **4 MiB stack**, Emscripten memory64/EH, explicit static roots and
the experimental runtime. Only the spill variant uses the private Binaryen
flattening/pointer-spill transform. That transform has known operand-stack
coverage gaps and exception-rooting limitations; this benchmark does not stress
exception payload lifetime and does not prove complete root discovery. The
ordinary unmodified Wasm startup remains unsupported. Passing these six
checksums is bounded evidence for this workload, not a general GC-safety or
Wasm-support claim.
