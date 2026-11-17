import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

for (const bits of [32, 64]) {
  const bytes = await readFile(`artifacts/wasm-probe/cpp-zig-${bits}.wasm`);
  const module = await WebAssembly.compile(bytes);
  assert.deepEqual(WebAssembly.Module.imports(module), []);
  const instance = await WebAssembly.instantiate(module);
  assert.equal(instance.exports.cpp_calls_zig(20, 22), 42n);
  assert.equal(instance.exports.cpp_calls_zig(2147483647, 2147483647), 4294967294n);
  assert.equal(instance.exports.cpp_calls_zig(-2147483648, -2147483648), -4294967296n);
  console.log(`Zig C++ -> Zig functions: wasm${bits} passed in Node`);
}
