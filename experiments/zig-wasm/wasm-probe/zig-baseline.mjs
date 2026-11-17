import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const bytes = await readFile("artifacts/spike.wasm");
const module = await WebAssembly.compile(bytes);
assert.deepEqual(WebAssembly.Module.imports(module), []);
const instance = await WebAssembly.instantiate(module);
assert.equal(instance.exports.spike_add(20, 22), 42n);
assert.equal(instance.exports.spike_add(2147483647, 2147483647), 4294967294n);
console.log("Standalone Zig Wasm works in Node, with no imported runtime functions");
