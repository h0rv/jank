# Research fork instructions

This checkout is a personal, AI-assisted jank research fork. Before changing code, read `CONTRIBUTING.md`, `JANK_WASM_PROMPT.md`, and `experiments/jank-wasm/README.md` in full.

Upstream forbids AI-generated external contributions, including code and prose. Keep this work in the fork. Do not submit it upstream as human-created work or remove its provenance to bypass that policy. Do not contact maintainers or open upstream pull requests without separate user authorization.

The branch starts from PR #1107 head `43ffa8d0a6bce1c17c552c6d46f4d6486dc304ed`. Preserve its history and credit. Push work only to the user's fork.

The optional native jank/Zig add-on and its reproduction commands are preserved on the `zig-addon` branch. Main retains the pure-jank build wrapper and mixed Wasm/GC research fixtures. Historical Zig spike results below refer to that branch. A wasm64 runtime archive and spike link exist; ordinary startup still fails. Static roots plus flattening and a private memory64/EH-cleanup Binaryen spill transform reach both spike markers with a larger diagnostic stack. The Emscripten compiler + WASI ABI shim + Wasmtime route also reaches both markers; it is not a native wasi-sdk runtime port. Runtime-owned scanned root cells now protect thrown object_ref and error_ref payloads through rethrow and exception_ptr ownership; all fourteen lifetime cases pass natively and with the wasm64 flatten/spill transform, without a harness exception-storage wrapper. Arbitrary native exceptions containing GC-managed fields are outside that ownership contract. These bounded experiments do not establish general Wasm support. Read the detailed evidence before reporting support or success.

Keep downloaded SDKs, build outputs and logs under the experiment's ignored directories. Do not replace global tools.
