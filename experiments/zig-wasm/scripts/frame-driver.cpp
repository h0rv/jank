// AI-assisted experimental empty-stack browser safepoints.
#include <cstdio>
#include <emscripten.h>
#include <jank/c_api.h>
#include <jank/gc.hpp>

extern "C" char __global_base, __data_end;
int jank_project_main(int argc, char const **argv);

namespace
{
  size_t frames{};

  [[gnu::noinline]] void invoke_frame()
  {
    jank_call0(jank_deref(jank_var_intern_c(JANK_FRAME_NS, JANK_FRAME_FN)));
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
  GC_add_roots(&__global_base, &__data_end);
  GC_disable();
  int const status{ jank_project_main(argc, argv) };
  if(status) { return status; }
  collect();
  emscripten_set_main_loop(frame, 0, 0);
  return 0;
}
