/* AI-assisted bounded single-thread WASI Preview 1 ABI bridge. */
typedef unsigned int u32;
typedef unsigned long long u64;
typedef long long i64;
#define HOST(name) __attribute__((import_module("wasi_snapshot_preview1"), import_name(#name)))
#define EXPORT(name) __attribute__((export_name(#name)))
HOST(fd_write) extern u32 host_write(u32,u32,u32,u32);
HOST(fd_read) extern u32 host_read(u32,u32,u32,u32);
HOST(fd_close) extern u32 host_close(u32);
HOST(fd_seek) extern u32 host_seek(u32,i64,u32,u32);
HOST(fd_fdstat_get) extern u32 host_fdstat(u32,u32);
HOST(args_sizes_get) extern u32 host_args_sizes(u32,u32);
HOST(args_get) extern u32 host_args(u32,u32);
HOST(environ_sizes_get) extern u32 host_env_sizes(u32,u32);
HOST(environ_get) extern u32 host_env(u32,u32);
HOST(clock_time_get) extern u32 host_clock(u32,u64,u32);
HOST(random_get) extern u32 host_random(u32,u32);
HOST(proc_exit) extern void host_exit(u32);
__attribute__((import_module("main"), import_name("wasi_shim_scratch"))) extern u64 scratch_address(void);

static u32 narrow(u64 p,u64 len) {
  if(p>0xffffffffULL || len>0xffffffffULL || p+len>0x100000000ULL) __builtin_trap();
  return (u32)p;
}
static u32 *scratch(void) {
  u64 p=scratch_address(); narrow(p,262144); return (u32*)p;
}
static u32 io(u32 fd,u64 vec,u64 count,u64 written,int read) {
  if(count>8192) __builtin_trap();
  narrow(vec,count*16); narrow(written,8);
  u32 *s=scratch();
  for(u64 i=0;i<count;i++) {
    u64 *v=(u64*)(vec+16*i);
    s[2*i]=narrow(v[0],v[1]); s[2*i+1]=(u32)v[1];
  }
  u32 *n=s+16384; *n=0;
  u32 status=read?host_read(fd,(u32)(u64)s,(u32)count,(u32)(u64)n)
                 :host_write(fd,(u32)(u64)s,(u32)count,(u32)(u64)n);
  if(!status) *(u64*)written=*n;
  return status;
}
EXPORT(fd_write) u32 write64(u32 fd,u64 vec,u64 count,u64 n) {return io(fd,vec,count,n,0);}
EXPORT(fd_read) u32 read64(u32 fd,u64 vec,u64 count,u64 n) {return io(fd,vec,count,n,1);}
EXPORT(fd_close) u32 close64(u32 fd) {return host_close(fd);}
EXPORT(fd_seek) u32 seek64(u32 fd,i64 offset,u32 whence,u64 result) {return host_seek(fd,offset,whence,narrow(result,8));}
EXPORT(fd_fdstat_get) u32 fdstat64(u32 fd,u64 result) {return host_fdstat(fd,narrow(result,24));}
static u32 sizes(u64 count,u64 bytes,int env) {
  narrow(count,8); narrow(bytes,8); u32 *s=scratch();
  u32 e=env?host_env_sizes((u32)(u64)s,(u32)(u64)(s+1)):host_args_sizes((u32)(u64)s,(u32)(u64)(s+1));
  if(!e) {*(u64*)count=s[0]; *(u64*)bytes=s[1];} return e;
}
EXPORT(args_sizes_get) u32 args_sizes64(u64 a,u64 b) {return sizes(a,b,0);}
EXPORT(environ_sizes_get) u32 env_sizes64(u64 a,u64 b) {return sizes(a,b,1);}
static u32 strings(u64 pointers,u64 data,int env) {
  u32 *s=scratch();
  u32 e=env?host_env_sizes((u32)(u64)s,(u32)(u64)(s+1)):host_args_sizes((u32)(u64)s,(u32)(u64)(s+1));
  if(e) return e;
  u32 count=s[0], bytes=s[1]; if(count>8192) __builtin_trap();
  narrow(pointers,(u64)count*8); narrow(data,bytes);
  e=env?host_env((u32)(u64)(s+4),(u32)data):host_args((u32)(u64)(s+4),(u32)data);
  if(!e) for(u32 i=0;i<count;i++) ((u64*)pointers)[i]=s[4+i];
  return e;
}
EXPORT(args_get) u32 args64(u64 a,u64 b) {return strings(a,b,0);}
EXPORT(environ_get) u32 env64(u64 a,u64 b) {return strings(a,b,1);}
EXPORT(clock_time_get) u32 clock64(u32 id,u64 precision,u64 out) {return host_clock(id,precision,narrow(out,8));}
EXPORT(random_get) u32 random64(u64 out,u64 size) {return host_random(narrow(out,size),(u32)size);}
EXPORT(proc_exit) void exit64(u32 code) {host_exit(code); __builtin_trap();}
/* No JavaScript views are cached by this native host bridge. */
EXPORT(emscripten_notify_memory_growth) void growth(u64 index) {(void)index;}
