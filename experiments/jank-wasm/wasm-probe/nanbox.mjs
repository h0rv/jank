import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const bytes = await readFile("artifacts/wasm-probe/nanbox64.wasm");
const { instance } = await WebAssembly.instantiate(bytes);
assert.equal(instance.exports.nanbox_round_trip(), 0);
console.log("wasm64: isolated jank-style tagged pointer round trip passed (no GC)");
