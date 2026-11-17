// AI-assisted: inspect actual shadow-stack bytes during direct/indirect callbacks.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pointer = 0xfffa000000001001n;
let instance;
let found;
let calls;
({ instance } = await WebAssembly.instantiate(readFileSync(process.argv[2]), {
  env: { collect() {
    calls++;
    found = false;
    const memory = new DataView(instance.exports.memory.buffer);
    for (let offset = Number(instance.exports.sp.value); offset < 4096; offset += 8) {
      found ||= memory.getBigUint64(offset, true) === pointer;
    }
    return 0;
  } },
}));
for (const name of ['direct', 'indirect', 'early', 'nonpointer', 'operand']) {
  const argument = name === 'nonpointer' ? 42 : BigInt.asIntN(64, pointer);
  calls = 0;
  assert.equal(instance.exports[name](argument), argument);
  assert.equal(calls, 1);
  assert.equal(instance.exports.sp.value, 4096n);
  if (['direct', 'indirect', 'early'].includes(name)) assert.equal(found, true);
  if (name === 'nonpointer') assert.equal(found, false);
  console.log(`SPILL COVERAGE: ${name} shadow-root=${found} stack-restored=true`);
}
