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
  __attribute__((weak)) int jank_wasm_between_frame_gc{};
}

namespace
{
  size_t frames{};

  // Disable automatic collections before ordinary C++ static initialization.
  __attribute__((constructor(101))) void disable_early_gc()
  {
    if(jank_wasm_between_frame_gc)
    {
      GC_disable();
      GC_set_finalize_on_demand(1);
    }
  }

  [[gnu::noinline]] void invoke_frame()
  {
    jank_call0(jank_deref(jank_var_intern_c(jank_wasm_frame_ns, jank_wasm_frame_var)));
  }

  void collect()
  {
    GC_enable();
    GC_gcollect();
    GC_disable();
    if(jank_wasm_between_frame_gc) { GC_invoke_finalizers(); }
  }

  void frame()
  {
    invoke_frame();
    ++frames;
    int const interval{ EM_ASM_INT({
      const n = Module.jankCollectEvery ?? $0;
      return Number.isInteger(n) && n >= 1 && n <= 60 ? n : 1;
    }, jank_wasm_between_frame_gc ? 30 : 1) };
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
  if(!jank_wasm_between_frame_gc) { GC_disable(); }
  int const status{ jank_project_main(argc, argv) };
  if(status) { return status; }
  collect();
  if(jank_wasm_frame_var) { emscripten_set_main_loop(frame, 0, 0); }
  return 0;
}
