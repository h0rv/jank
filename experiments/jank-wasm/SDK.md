# Offline wasm64 SDK (AI-assisted research)

After the research prerequisites have finished building, assemble the Linux
x86_64 package with:

```sh
./jank-build sdk
```

The package is written to `artifacts/sdk/jank-wasm-sdk-linux-x86_64/` and a
matching `.tar.gz`. Assembly uses the existing build container; using the
extracted SDK does not use Docker or download dependencies.
The measured compressed package is approximately 580 MiB.

On Linux x86_64 with Python 3.10 or newer and a POSIX shell:

```sh
tar -xzf jank-wasm-sdk-linux-x86_64.tar.gz
./jank-wasm-sdk-linux-x86_64/bin/jank-wasm build /path/to/project
./jank-wasm-sdk-linux-x86_64/bin/jank-wasm run /path/to/project
./jank-wasm-sdk-linux-x86_64/bin/jank-wasm serve /path/to/project --port 8765
```

A project supplies `jank-build.json`, for example
`{"name":"hello","main":"hello.core","jank":"src"}`. The optional `frame`
is a qualified zero-argument var; `libraries` accepts the bundled `raylib`.
Existing `include_dirs`, target link flags, and output expectations are also
understood. There is no package/dependency resolver. Outputs are
`dist/wasm/{name.js,name.wasm,index.html}` inside the project. `run` uses the
bundled Node; interactive applications should use `serve` instead.

The SDK contains the host compiler, matching shared libraries and glibc loader,
host analysis headers and source resources, wasm64 runtime and prebuilt entry
archives, target headers and SDK-relative compilation flags, patched Binaryen,
Emscripten 7.0.0 with its LLVM tools and prebuilt system-library cache, Node
26.13.1, the raylib archives, and the browser page template. The host adapter
calls the existing resource-directory C API before compiler startup; launcher
generation uses C++ output and syntax checking, not a native application link.
No compiler, language, or object-model changes are involved.

Static-root registration is generated and linked automatically. The common
entry disables collection while jank executes and collects at empty-stack
safepoints; configured browser frames retain the collection cadence and stats
API. Synchronous raylib applications use the separate prebuilt loop adapter.
The driver applies the experimental flatten/spill post-link pass internally.

Limits: wasm64 only; Chrome/Node must support memory64 and Wasm exceptions
(synchronous browser loops also require JSPI). This is the experimental
spill/static-root GC path, not general Wasm or GC-safety support. It does not
provide runtime evaluation, threads, a general browser API, or arbitrary native
exception rooting. Extract to a writable directory whose path contains no
whitespace; the unchanged host JIT flag parser splits on spaces. Projects and
the extracted SDK must be writable for staging and compiler caches.
