import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const load = async (name, imports = {}) => (await WebAssembly.instantiate(readFileSync(name), imports)).instance.exports;
const gcModule = await load(process.argv[2] + '/gc.wasm');
console.log('node', process.version);
const samples = [];
for (let batch = 0; batch < 8; ++batch) {
  assert.equal(gcModule.churn(2_000_000), 1_999_999);
  // No forced GC: V8 must manage the transient Wasm objects itself.
  samples.push(Math.round(process.memoryUsage().rss / 1024 / 1024));
}
console.log('GC: 16000000 cons + 16000000 boxes; result=1999999; RSS MiB=' + samples.join(','));
assert.ok(Math.max(...samples.slice(2)) - Math.min(...samples.slice(2)) < 96, 'RSS did not plateau within diagnostic tolerance');
const refs = await load(process.argv[2] + '/refs.wasm');
refs.init();
const object = { value: 42 };
assert.equal(refs.pass(object), object);
refs.put(object); assert.equal(refs.get(), object); refs.clear(); assert.equal(refs.get(), null);
console.log('externref: identity/table retain/clear PASS');
const hybrid = await load(process.argv[2] + '/hybrid.wasm', { gc: gcModule });
hybrid.init();
assert.equal(hybrid.hybrid(41), 42);
assert.equal(hybrid.hybrid(-1), 0);
assert.throws(() => gcModule.read(null), WebAssembly.RuntimeError);
const n = 1_000_000;
let start = performance.now();
for (let i = 0; i < n; ++i) hybrid.hybrid(i);
console.log(`hybrid: result=42, zero-result=0, null cast traps PASS; ${n} JS->C->GC calls ms=${(performance.now()-start).toFixed(2)}`);
