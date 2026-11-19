# Wasm GC research probes (AI-assisted, fork only)

Run `bash run.sh` with Node 24 and an isolated Emscripten SDK at
`/home/ubuntu/tools/emsdk` (or set `EMSDK`). Outputs go to ignored
`../artifacts/wasm-gc-probe/`. No jank runtime build is required.

`gc.wat` allocates real engine-managed structs, not linear-memory objects.
The RSS plateau is a bounded observation, not a collector proof or heap-size API.
`refs.cpp` exercises Clang's special table-only reference arrays and rejects
ordinary object fields, heap allocation, externally linked arrays and addresses.
`hybrid.c` keeps only an integer handle in a linear-memory C struct; a Wasm
table roots its GC box. Clearing the slot releases that root. A production
implementation needs slot allocation/reuse, bounds checking, ownership and
exception-safe cleanup. Its timed loop includes JS entry and allocation, so is
not an isolated measurement of table overhead.

See `REPORT.md` for tool versions, source evidence and captured results.
