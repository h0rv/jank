// AI-assisted: inspect actual shadow-stack bytes during direct/indirect callbacks.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pointer = 0xfffa000000001001n;
let instance;
let allFound;
let calls;
({ instance } = await WebAssembly.instantiate(readFileSync(process.argv[2]), {
  env: { collect() {
    calls++;
    let found = false;
    const memory = new DataView(instance.exports.memory.buffer);
    for (let offset = Number(instance.exports.sp.value); offset < 4096; offset += 8) {
      found ||= memory.getBigUint64(offset, true) === pointer;
    }
    allFound &&= found;
    return 0;
  } },
}));
for (const name of ['direct', 'indirect', 'early', 'nonpointer', 'operand', 'unwind']) {
  const argument = name === 'nonpointer' ? 42 : BigInt.asIntN(64, pointer);
  calls = 0;
  allFound = true;
  assert.equal(instance.exports[name](argument), argument);
  assert.equal(calls, name === 'unwind' ? 20000 : 1);
  assert.equal(instance.exports.sp.value, 4096n);
  assert.equal(allFound, name !== 'nonpointer');
  if (name === 'unwind') {
    console.log(`SPILL UNWIND: iterations=10000 catch-stack-drift=${instance.exports.drift.value}`);
    assert.equal(instance.exports.drift.value, 0n);
  }
  console.log(`SPILL COVERAGE: ${name} shadow-root=${allFound} stack-restored=true`);
}
