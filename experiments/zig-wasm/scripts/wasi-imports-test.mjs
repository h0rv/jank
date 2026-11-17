// AI-assisted normal, empty and rejected-input checks for import rewriting.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out=path.join(root, 'artifacts/wasi-probes/import-tests');
fs.mkdirSync(out, {recursive:true});
const header=Buffer.from([0,97,115,109,1,0,0,0]);
const name=s=>Buffer.concat([Buffer.from([s.length]),Buffer.from(s)]);
function moduleWithImport(module,field,kind=0) {
  const payload=Buffer.concat([Buffer.from([1]),name(module),name(field),Buffer.from([kind,0])]);
  return Buffer.concat([header,Buffer.from([2,payload.length]),payload]);
}
function rewrite(bytes) {
  const input=path.join(out,'input.wasm'),output=path.join(out,'output.wasm');
  fs.writeFileSync(input,bytes);
  const run=spawnSync(process.execPath,[path.join(root,'scripts/wasi-imports.mjs'),input,output],{encoding:'utf8'});
  return {...run,bytes:run.status===0?fs.readFileSync(output):null};
}
test('rewrites supported WASI and env imports',()=>{
  for(const [module,field] of [['wasi_snapshot_preview1','fd_write'],['env','emscripten_notify_memory_growth']]) {
    const result=rewrite(moduleWithImport(module,field));
    assert.equal(result.status,0,result.stderr);
    assert.equal(JSON.parse(result.stdout)[0].field,field);
    assert.ok(result.bytes.includes(Buffer.from('shim_snapshot_preview1')));
  }
});
test('preserves a module without imports',()=>{
  const result=rewrite(header);
  assert.equal(result.status,0,result.stderr);
  assert.deepEqual(JSON.parse(result.stdout),[]);
  assert.deepEqual(result.bytes,header);
});
test('rejects unknown imports and malformed binaries',()=>{
  for(const bytes of [moduleWithImport('env','unknown'),moduleWithImport('wasi_snapshot_preview1','unknown'),
    moduleWithImport('env','memory',2),Buffer.alloc(0),Buffer.concat([header,Buffer.from([2,128])])]) {
    const result=rewrite(bytes);
    assert.notEqual(result.status,0);
    assert.match(result.stderr,/Unimplemented import|non-function import|Invalid/);
  }
});
