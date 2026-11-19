# Wasm size attribution and release-build measurements

AI-assisted build-configuration experiment, 2026-11-19. No changes to jank's
compiler, runtime, language, app sources, or dependency pins. Nothing published.

## Step 2: locally built variants

**Selected default: C with `-Oz` after spilling, plus app compilation `-Os`,
without LTO.** This was smallest in raw, gzip and Brotli among the measured
variants. Both demos passed the headless Chrome/GC checks below. Relative to
the published baseline, live is 59.78% smaller raw / 60.89% gzip / 58.77% Brotli;
the game is 60.32% smaller raw / 60.86% gzip / 58.84% Brotli.

### Before/after and variant matrix

Decimal MB. Each size cell is **raw / gzip -9 / Brotli 11**. Every row was
built or derived from a local build and both modules were run in Chrome.

| Variant | live MB | flappy-bird MB |
|---|---:|---:|
| A: published build flags, app `-O2` | 19.562484 / 2.768486 / 1.930697 | 20.297229 / 2.907130 / 2.047416 |
| B: release link + strip after spill, app `-O2` | 9.730894 / 1.334130 / 0.937786 | 9.990794 / 1.401768 / 0.993977 |
| C: B + DCE/size passes, `-Os` post-spill | 8.134288 / 1.111503 / 0.805202 | 8.336367 / 1.168727 / 0.852947 |
| C: B + DCE/size passes, `-Oz` post-spill | 7.903267 / 1.092203 / 0.799669 | 8.104316 / 1.150581 / 0.847326 |
| C: B + `--dce -O3` and unused-element/name removal | 8.450310 / 1.137168 / 0.810894 | 8.657893 / 1.195761 / 0.857616 |
| D: C `-Oz` + app/link `-flto` | 7.903727 / 1.090061 / 0.797330 | 8.105548 / 1.146007 / 0.844525 |
| B, app compile `-Os` instead of `-O2` | 9.685159 / 1.325126 / 0.933118 | 9.925091 / 1.389973 / 0.987296 |
| **Selected: C `-Oz`, app compile `-Os`** | **7.868063 / 1.082735 / 0.795938** | **8.054059 / 1.137910 / 0.842782** |

Started a full background `scripts/build-pages.sh` build from the clean shallow
checkout described below. It bootstrapped `jank-host-build` (ubuntu:24.04), host
compiler, native and wasm64 runtime archives, SDK, patched Binaryen, raylib, both
native demos and both Wasm demos, and assembled Pages successfully. Both A
Wasm hashes reproduced the published binaries **byte-for-byte** (hashes below).
Subsequent variants reused the unchanged runtime archive and generated C++;
B, D and app-Os recompiled/relinked app code. C was independently postprocessed
from B for each optimization level (not cumulative Os → Oz → O3).

B drops app compile `-g` and link `-g`/`--profiling-funcs`, but uses **`-g2`
only at link** to preserve names needed by the spill transform to find
`__stack_pointer`. Unlike `-g`, this does not request DWARF or inhibit normal
Emscripten post-link optimization. The spill pass still serializes with `-g`;
a subsequent pass strips debug/name/producers sections from the final module.
Thus B saves more than simply deleting the published binary's custom sections:
normal Emscripten link optimizations now run **before** flatten/spill.

C runs these passes **after** the existing flatten/spill/local-compaction step:

```text
--strip-debug --strip-producers --dce --remove-unused-module-elements
--remove-unused-names -Os    # or independently -Oz / -O3
```

All Binaryen calls use the same explicit memory64/legacy-EH/bulk-memory/
mutable-globals/nontrapping-conversion/sign-extension/reference-types/multivalue
features as the spill helper, never `--all-features`. No stripping happens before
the spill transform. No GC/rooting pass was removed or replaced. These post-spill
optimizations are semantically substantial; the bounded GC checks below are a
regression check, **not a proof** that optimized code preserves every possible
pointer carrier/root lifetime for arbitrary jank programs.

### LTO result

D successfully compiled app/launcher/adapter objects with `-flto`, linked with
`-flto -O2 -g2` and completed spill plus `-Oz` for **both** demos. Emscripten
built its LTO system-library variants (including libc++/ABI) as part of that link.
There was no LTO compile/link failure. Both demos passed the same GC checks.

This is **app + Emscripten system-library LTO**, not a rebuilt LTO jank runtime:
the existing runtime/core AOT archive remained machine-code Wasm. The runtime
CMake file unconditionally sets `CMAKE_INTERPROCEDURAL_OPTIMIZATION FALSE`
(`compiler+runtime/CMakeLists.txt:18-19`), so it does not expose an effective
runtime LTO option to turn on with that cache variable alone. Chose the allowed
app/link LTO experiment rather than edit that source or rebuild the runtime with
manually injected `-flto` CMake flags. Full runtime/core-LTO gains remain unmeasured.

D is slightly larger raw than C-Oz, with only 2.1/4.6 kB gzip and 2.3/2.8 kB
Brotli savings. App `-Os` + C-Oz is smaller in **all three** measures than D, so
the selected default does not require LTO. `-O3` post-spill was larger than both
size-optimized levels; it was measured and GC-validated, not selected.

### Browser and GC validation

Chrome for Testing **156.0.8078.47**, headless, SwiftShader WebGL2, JSPI enabled
by the current browser. The CDP harness follows the existing
`scripts/check-tetris-browser.mjs` approach, serving each variant's matching JS
and Wasm together. For live it presents an input/button, clicks Run for 200000,
then changes the input to 10000 and runs again. Every variant returned exactly:

```text
17984 primes below 200000
1229 primes below 10000
```

Live uses its existing empty-stack safepoint collector, with
`jankCollectEvery=1`. The game retains **in-call GC** and the unchanged raylib
loop driver; the harness clicks New game, runs at least 300 additional frames
(~5 seconds), verifies increasing `GC_get_gc_no()`, reads back a rendered frame
(56 distinct colors, WebGL error 0), and captures a screenshot. Every browser
run recorded zero JS/Wasm exceptions, no abort/unreachable/OOB console traps.
The rendered selected variant was also visually inspected: game canvas plus
score/game-over state; live input and streaming prime-count output.

| Variant | live GC count → final; final frames | game GC count → final; final frames | First frame live / game, ms |
|---|---|---|---:|
| A | 8 → 311; 309 | 15 → 19; 307 | 810.8 / 596.1 |
| B | 9 → 310; 308 | 14 → 19; 307 | 599.4 / 729.6 |
| C-Os | 7 → 307; 305 | 14 → 19; 306 | 942.0 / 926.2 |
| C-Oz | 7 → 307; 305 | 14 → 19; 306 | 877.6 / 974.2 |
| C-O3 | 7 → 307; 305 | 14 → 19; 307 | 856.0 / 650.6 |
| D | 8 → 308; 306 | 14 → 19; 308 | 1189.6 / 656.2 |
| B + app-Os | 7 → 308; 306 | 14 → 19; 306 | 1071.5 / 552.5 |
| **Selected: app-Os + C-Oz** | **8 → 310; 308** | **14 → 19; 308** | **507.6 / 553.0** |

First-frame times are single local measurements with warm HTTP/tool caches and
varying concurrent build/optimizer CPU load, measured from navigation script to
first frame callback. They are **not** a controlled startup-performance comparison.
There is no statistically supported startup-speed claim here.

Selected artifacts, relative to `experiments/zig-wasm/`:

* `artifacts/size/app-Os-Oz/live.png`, `flappy-bird.png`
* `artifacts/size/app-Os-Oz/{live,flappy-bird}.browser.json` and `.console.log`
* Wasm SHA256 live: `38992f9c00efa502fc88b17bf160049072596ed2ec5610009f8af5a5d165c023`
* Wasm SHA256 game: `28efd7780a481636bac7def11c6722e086bb9813c50e59578a9ae1e2dc55386d`

All variants retain their binaries, per-module sizes/hashes, browser JSON,
screenshots and console logs under ignored `artifacts/size/<variant>/`.
Variant labels there are A, B, C-Os, C-Oz, C-O3, D, app-Os and app-Os-Oz.
Bootstrap/build logs are in `artifacts/size/baseline-build.log`, per-variant
`*-build.log`, and `artifacts/logs/app/` (per compile/link/spill).

### Build defaults, reproduction and scope

`scripts/jank-build.py:374-421` now defaults to app `-Os`, link `-O2 -g2` without
profiling, existing spill/local compaction, then C's `-Oz` pipeline.
`wasm-probe/spill-pointers.py:9-33` adds the selected post-spill mode while
preserving the old baseline behavior for standalone callers with no mode argument.
`build-pages.sh` needs no edit: it already uses jank-build for both demos and
copies only final modules, preserving the cache-busting scheme.

From `experiments/zig-wasm/`, the new default full build is still:

```sh
bash scripts/build-pages.sh
```

Experiment switches accepted by the driver:

* `JANK_WASM_BUILD_MODE=baseline`: original flags, app default `-O2`, no final strip.
* `JANK_WASM_BUILD_MODE=strip JANK_WASM_APP_OPT=-O2`: B.
* `JANK_WASM_BUILD_MODE=Os|Oz|O3 JANK_WASM_APP_OPT=-O2`: C variants.
* `JANK_WASM_BUILD_MODE=Oz JANK_WASM_APP_OPT=-O2 JANK_WASM_LTO=1`: D.
* `JANK_WASM_BUILD_MODE=strip JANK_WASM_APP_OPT=-Os`: app-Os comparison.
* No switches: selected app-Os + C-Oz. LTO is off unless explicitly set to `1`.

The `Os|Oz|O3` notation above means choose one value, not a literal shell pipe.
For these measurements `artifacts/size/rebuild.py` reused baseline generated
sources and called the driver's actual `build_wasm` in isolated output dirs;
`variants.mjs` applied each post-spill pass set independently in the container;
`compress.mjs` used Node's gzip-9/Brotli-11; `browser.mjs` performed CDP checks.
These investigation scripts remain ignored, not product build APIs.

The first attempted host invocation of the container-built wasm-opt failed with
`GLIBC_2.38`/`GLIBCXX_3.4.32` version errors. Corrected the investigation runner
to execute it inside `jank-host-build`; all measured transforms use the container.
MEMORY64 deprecation and baseline limited-DWARF-optimization warnings were
expected SDK diagnostics, not evidence of an unloaded environment.

Regression tests cover default/explicit modes, app/link flags, LTO forwarding,
invalid/empty size options, and spill-before-strip/optimization ordering.
No jank runtime/compiler sources or CMake files were edited. No public site
deployment or push was performed. Full runtime LTO, general GC safety, long
game sessions and controlled performance benchmarking remain outside this result.

## Step 1: published baseline measurement (archived)

The remaining section records the initial measurement before Step 2. Build
references in it refer to the original checkout revision, not the edited scripts.

AI-assisted measurement, 2026-11-19. No compiler/runtime/language changes.
All MB below are decimal (1,000,000 bytes). Percentages in the component table
are of encoded **function bodies**, not compressed bytes or total module size.

## Inputs and scope

Downloaded the actual public `http://horv.co/jank-wasm/{live,flappy-bird}.wasm`
without requesting transfer compression. These are the two modules loaded by
the current index page and its runners; the former hello example has been
replaced by the interactive prime-counting `live` example. HTTPS `hello.wasm`
returned 404. `app.wasm` returned 503 and is only mentioned schematically on the
research page, not loaded by either runner. There is no measured hello binary.
No local build was necessary, and no compilation/execution/correctness claim is
made. No visual check was needed for this binary measurement.

The requested clone was absent on this machine. Created a shallow main checkout
of h0rv/jank-wasm at `f569a86abf38b2c04b534424e783132245f352fd`; no unshallow
fetch was started. No Docker containers were running. Build flags below describe
this checkout's scripts, not independently recovered provenance of the deployed
binary (there is no checked deployment linker map).

SHA256:

* live: `53dfacbf35c26f2a6a78db2bc41c4d8e1048a6be8128d800b35feecf3c4a4ed4`
* flappy-bird: `b5b3458a5f80ff1f6e35d646a5d97284cc507dcd5fe599b2c06a14d43c45e7c4`

## Download sizes

| Module | Raw bytes (MB) | gzip level 9 bytes (MB) | Brotli quality 11 bytes (MB) |
|---|---:|---:|---:|
| live | 19,562,484 (19.562) | 2,768,486 (2.768) | 1,930,697 (1.931) |
| flappy-bird | 20,297,229 (20.297) | 2,907,130 (2.907) | 2,047,416 (2.047) |

Compression measured locally using Node's zlib, not inferred from HTTP
Content-Length or the site's rounded table. It is not a measurement of current
CDN content-encoding. gzip numbers can differ slightly by implementation/header.

## Section breakdown

Includes each section's id/length framing and custom-section name, so columns
plus the eight-byte module header sum exactly to the downloaded byte counts.

| Section | live bytes | flappy-bird bytes |
|---|---:|---:|
| code | 12,221,529 | 12,461,420 |
| data | 558,249 | 586,065 |
| name | 1,727,001 | 1,741,661 |
| .debug_loc | 769,309 | 875,226 |
| .debug_abbrev | 122,950 | 134,070 |
| .debug_info | 2,074,690 | 2,187,885 |
| .debug_ranges | 172,530 | 184,546 |
| .debug_str | 1,382,067 | 1,503,705 |
| .debug_line | 516,093 | 590,723 |
| .debug_aranges | 210 | 210 |
| all other standard sections | 17,848 | 31,710 |
| header | 8 | 8 |

No other custom sections were present. Debug totals: 5,037,849 and 5,476,365
bytes. Data is the encoded data section, **not** runtime heap or memory capacity.
It is not attributed to libraries here; function names cannot attribute data.

## Code attribution

Decoded the code section's individual body lengths (including local declarations
and instructions, excluding each body's length prefix) and paired their indices
with the function-name subsection, accounting for imported function indices.
All 9,485 live and 9,643 game function bodies have names. Body totals are
12,204,490 and 12,444,101 bytes. Binaryen 133 `--metrics` independently reports
the same function counts. Metrics instruction counts are not byte sizes.

| Named-body component | live MB (% code) | flappy-bird MB (% code) |
|---|---:|---:|
| clojure.core AOT | 6.4520 (52.87%) | 6.4559 (51.88%) |
| jank runtime / support | 4.1095 (33.67%) | 4.1144 (33.06%) |
| libc++ namespace functions | 0.9659 (7.91%) | 0.9660 (7.76%) |
| Boost | 0.2048 (1.68%) | 0.2017 (1.62%) |
| app AOT | 0.0924 (0.76%) | 0.1855 (1.49%) |
| libc + other C / unresolved | 0.1070 (0.88%) | 0.1240 (1.00%) |
| raylib / raygui named functions | 0 | 0.1102 (0.89%) |
| bdwgc named functions | 0.1058 (0.87%) | 0.1056 (0.85%) |
| Immer | 0.0841 (0.69%) | 0.0841 (0.68%) |
| Folly | 0.0421 (0.34%) | 0.0421 (0.34%) |
| C/C++ ABI / compiler / Emscripten named functions | 0.0294 (0.24%) | 0.0443 (0.36%) |
| other / unresolved | 0.0117 (0.10%) | 0.0103 (0.08%) |

**Attribution is a symbol-name estimate, not original-object/library accounting.**
Rules: `clojure_core$*` and `jank_load_clojure_core*` are core AOT; app namespace
and loader prefixes are app; demangled functions use the first recognized
namespace among jank/jtl/std/boost/immer/folly/fmt. jank C API and C++ global
initializers are support. `GC_*`/`alloc_mark_stack` identify collector bodies.
Game `rl[A-Z]*`, `Gui[A-Z]*`, `stbi*`, `qoi_*` and capitalized C function names
identify raylib/raygui. ABI/Emscripten prefixes are separated; remaining C names
are deliberately not all claimed as libc. No separate fmt row was matched.

Templates with return types from another library can be classified under that
namespace. Inlined library code belongs to its containing body, e.g. core AOT
can include runtime/container operations. bdwgc and raylib internal unprefixed
helpers can be in unresolved C. Thus small-library rows are not exact library
totals; a linker map/object-level rebuild would refine those boundaries, but
would measure a new build rather than prove the published binary's provenance.
JS imports/glue are outside Wasm function-body byte accounting.

Largest live bodies (game nearly identical):

| Function | MB | % live code |
|---|---:|---:|
| jank_load_clojure_core | 0.623808 | 5.11% |
| clojure_core$with_out_str_34631_3 | 0.577176 | 4.73% |
| clojure_core$emit_bind_33802_1 | 0.570393 | 4.67% |
| jank_load_clojure_core_0 | 0.507177 | 4.16% |
| clojure_core$step_33442_2 | 0.415316 | 3.40% |
| clojure_core$pmap_33710_3 | 0.255609 | 2.09% |

Largest game app body is `org_jank_lang_example_flappy_bird$draw_frame_BANG__353_1`
(74,210 bytes); largest live app body is `live_core$step_120_1` (37,822).
Core plus runtime/support account for ~86%/~85% of named code respectively;
this does **not** establish that these functions are removable/dead.

## Strip-only estimate

For an exact estimate, copied the binary header and every standard section
unchanged, dropping only custom `name` and `.debug_*` sections. No code passes,
feature rewriting or relinking. Results:

| Module | Raw after | gzip -9 after | Raw reduction | gzip reduction |
|---|---:|---:|---:|---:|
| live | 12,797,634 | 1,445,198 | 6,764,850 (34.58%) | 1,323,288 (47.80%) |
| flappy-bird | 13,079,203 | 1,516,082 | 7,218,026 (35.56%) | 1,391,048 (47.85%) |

Also ran stock Binaryen 133 `wasm-opt INPUT --all-features --strip-debug -o COPY`:
live 12,718,627 raw / 1,438,327 gzip; game 12,996,711 raw / 1,509,076 gzip.
These are slightly smaller than exact section deletion because Binaryen rewrites
the module. Do not credit that extra difference to debug stripping alone.
`--all-features` is for this analysis copy only (may change feature encoding);
it is **not** a recommendation for deployable output. Copies were not executed.

## Current build pipeline (source inspection)

Paths relative to repository root:

* `experiments/zig-wasm/scripts/build-pages.sh:6-14`: builds `examples/live-demo`
  and `examples/flappy-bird` via `jank-build`, copies only their final Wasm/JS.
* `experiments/zig-wasm/jank-build:4` dispatches to `scripts/jank-build.py`.
  Its lines 25 and 177-183 require/validate the `jank-host-build` ubuntu:24.04
  container with the same-path repository mount.
* `experiments/zig-wasm/scripts/build-wasm64-target.sh:76-92`: target runtime
  CMake Release, memory64, Wasm exceptions, cross compilation, host phase-1
  compiler, threads disabled. `compiler+runtime/CMakeLists.txt:155-157` specifies
  Release `-O2 -DNDEBUG`, core optimization `-O3`.
* `compiler+runtime/CMakeLists.txt:18-19`: explicitly disables CMake IPO/LTO.
  App compile/link commands add no `-flto`. No LTO run was observed or performed.
* `experiments/zig-wasm/scripts/jank-build.py:362-393`: inherits target runtime
  flags from compile_commands.json, then app generated C++ compiles `-O2 -g`.
* Same file lines 404-410: link `-O2 -g --profiling-funcs -sMEMORY64=1
  -fwasm-exceptions -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=4194304`, plus project
  flags; synchronous raylib adds `-sJSPI=1 -Wl,--wrap=EndDrawing`.
  Live config (`examples/live-demo/jank-build.json:2-6`) sets a frame callback
  and `-sMODULARIZE=1 -sEXPORT_NAME=createLive`; game links raylib
  (`examples/flappy-bird/jank-build.json:2-6`).
* `experiments/zig-wasm/scripts/build-raylib.sh:41-46`: raylib WebGL ES3 web
  build with memory64/exceptions; raygui compiled `-O2`. The makefile supplies
  raylib's own optimization default; not recovered from a build log here.
* `experiments/zig-wasm/scripts/jank-build.py:411` invokes
  `wasm-probe/spill-pointers.py`; lines 13-22 of that helper preserve an
  `.unspilled.wasm` then run private patched Binaryen:
  `--flatten --spill-pointers --reorder-locals --coalesce-locals --reorder-locals -g`
  with explicit input features. No additional `-O`, `-Oz` or strip pass follows.
  Stock Binaryen used for this report is **not** that patched spill optimizer.

The sizeable published name/debug sections agree with this diagnostic `-g`
pipeline. Exact tool invocations of the deployment itself remain unverified.

## Reproduction artifacts and checks

Ignored `experiments/zig-wasm/artifacts/size/` contains downloaded originals,
`measure.mjs` (section parser/body sizes/compression), `summarize.mjs` (classification),
per-module JSON including every named function, component JSON, Binaryen metrics,
and both stripping variants. Binaryen 133 was downloaded under ignored `.tools/`;
no system tooling was installed. Node built-in zlib supplies compression.

Commands from repository root:

```sh
node experiments/zig-wasm/artifacts/size/measure.mjs
node experiments/zig-wasm/artifacts/size/summarize.mjs
experiments/zig-wasm/.tools/binaryen-version_133/bin/wasm-opt \
  experiments/zig-wasm/artifacts/size/live.wasm --all-features --metrics -o /dev/null
```

Printed checks (both modules): `section total check true`; all defined functions
have names, and body counts equal Binaryen's metrics. No source tests were run
because this step changes only this report and ignored measurement artifacts.
No browser execution, stripped-output correctness test, local bootstrap, linker
map generation or dead-code/reachability analysis was attempted.
