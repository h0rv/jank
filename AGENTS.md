# Research fork instructions

This checkout is a personal, AI-assisted jank research fork. Before changing code, read `CONTRIBUTING.md`, `ZIG_WASM_PROMPT.md`, and `experiments/zig-wasm/README.md` in full.

Upstream forbids AI-generated external contributions, including code and prose. Keep this work in the fork. Do not submit it upstream as human-created work or remove its provenance to bypass that policy. Do not contact maintainers or open upstream pull requests without separate user authorization.

The branch starts from PR #1107 head `43ffa8d0a6bce1c17c552c6d46f4d6486dc304ed`. Preserve its history and credit. Push work only to the user's fork.

Native jank/Zig checks and small Wasm probes exist. A wasm64 runtime archive and spike link exist; ordinary startup still fails, but static roots with a private memory64-patched Binaryen spill transform pass the seven lifetime cases and reach both spike markers. These bounded experiments do not establish general Wasm support. Read the detailed evidence before reporting support or success.

Keep downloaded SDKs, build outputs and logs under the experiment's ignored directories. Zig is pinned to 0.17.1 for these probes. Do not silently upgrade it or replace global tools.
