import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { WASI } from "node:wasi";

const wasi = new WASI({ version: "preview1", args: [], env: {}, preopens: {} });
const module = await WebAssembly.compile(await readFile("artifacts/wasm-probe/stdlib32.wasm"));
const instance = await WebAssembly.instantiate(module, wasi.getImportObject());
wasi.initialize(instance);
assert.equal(instance.exports.cpp_vector_sum(0), 0n);
assert.equal(instance.exports.cpp_vector_sum(10), 45n);
assert.equal(instance.exports.cpp_vector_sum(1024), 523776n);
assert.equal(instance.exports.cpp_vector_sum(-1), -1n);
for (let i = 0; i < 10000; ++i) {
  assert.equal(instance.exports.cpp_vector_sum(100), 4950n);
}
console.log("C++ wasm32: std::vector allocation/destruction passed in Node WASI");
