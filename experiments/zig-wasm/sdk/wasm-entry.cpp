// AI-assisted experimental empty-stack application entry.
#include <emscripten.h>
#include <jank/c_api.h>
#include <jank/gc.hpp>

int jank_project_main(int argc, char const **argv);
extern "C"
{
  void jank_wasm_register_roots();
  __attribute__((weak)) char const *jank_wasm_frame_ns{};
  __attribute__((weak)) char const *jank_wasm_frame_var{};
}

namespace
{
  size_t frames{};

  [[gnu::noinline]] void invoke_frame()
  {
    jank_call0(jank_deref(jank_var_intern_c(jank_wasm_frame_ns, jank_wasm_frame_var)));
  }

  void collect()
  {
    GC_enable();
    GC_gcollect();
    GC_disable();
  }

  void frame()
  {
    invoke_frame();
    ++frames;
    int const interval{ EM_ASM_INT({
      const n = Module.jankCollectEvery ?? 1;
      return Number.isInteger(n) && n >= 1 && n <= 60 ? n : 1;
    }) };
    if(frames % interval == 0) { collect(); }
    EM_ASM({
      Module.jankFrameStats = ({frames: Number($0), collections: Number($1),
        heap: Number($2), used: Number($3), memory: HEAPU8.buffer.byteLength,
        time: performance.now(), collectEvery: $4});
      Module.onJankFrame?.(Module.jankFrameStats);
    }, frames, GC_get_gc_no(), GC_get_heap_size(),
       GC_get_heap_size() - GC_get_free_bytes(), interval);
  }
}

int main(int argc, char const **argv)
{
  GC_init();
  jank_wasm_register_roots();
  GC_disable();
  int const status{ jank_project_main(argc, argv) };
  if(status) { return status; }
  collect();
  if(jank_wasm_frame_var) { emscripten_set_main_loop(frame, 0, 0); }
  return 0;
}
