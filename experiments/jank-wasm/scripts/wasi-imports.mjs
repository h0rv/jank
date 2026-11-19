// AI-assisted import inspection/namespace rewrite; standard function imports only.
import fs from 'node:fs';
const [input,output]=process.argv.slice(2);
const data=fs.readFileSync(input);
if(!data.subarray(0,8).equals(Buffer.from([0,97,115,109,1,0,0,0]))) throw new Error('Invalid Wasm header');
let pos=8;
function leb() {
  let n=0,shift=0,b;
  do {
    if(pos>=data.length || shift>=35) throw new Error('Invalid u32 LEB');
    b=data[pos++]; n+=(b&127)*2**shift; shift+=7;
  }while(b&128);
  if(n>0xffffffff) throw new Error('Invalid u32 LEB');
  return n;
}
function enc(n) {const a=[];do {let b=n%128;n=Math.floor(n/128);a.push(b|(n?128:0));}while(n);return Buffer.from(a);}
function str() {const n=leb(),s=data.subarray(pos,pos+n);pos+=n;if(pos>data.length)throw new Error('Truncated name');return s.toString();}
function name(s) {const b=Buffer.from(s);return Buffer.concat([enc(b.length),b]);}
const supported=new Set(['fd_write','fd_read','fd_close','fd_seek','fd_fdstat_get',
  'args_sizes_get','args_get','environ_sizes_get','environ_get','clock_time_get','random_get','proc_exit']);
const chunks=[data.subarray(0,8)], imports=[];
while(pos<data.length) {
  const start=pos,id=data[pos++],size=leb(),end=pos+size;
  if(end>data.length)throw new Error('Truncated section');
  if(id!==2) {chunks.push(data.subarray(start,end));pos=end;continue;}
  const count=leb(), fields=[enc(count)];
  for(let i=0;i<count;i++) {
    const module=str(),field=str(),begin=pos,kind=data[pos++];
    if(kind!==0) throw new Error('Unsupported non-function import '+module+'::'+field);
    const type=leb();
    imports.push({module,field,type});
    if(!(module==='wasi_snapshot_preview1'&&supported.has(field))&&
       !(module==='env'&&field==='emscripten_notify_memory_growth'))
      throw new Error('Unimplemented import '+module+'::'+field);
    fields.push(name('shim_snapshot_preview1'),name(field),data.subarray(begin,pos));
  }
  const section=Buffer.concat(fields); chunks.push(Buffer.from([2]),enc(section.length),section);
  if(pos!==end)throw new Error('Import parse mismatch');
}
console.log(JSON.stringify(imports,null,2));
fs.writeFileSync(output,Buffer.concat(chunks));
