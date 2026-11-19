// AI-assisted host adapter for an unchanged synchronous raylib application.
// The link wraps emscripten_sleep with scripts/jspi-suspend-guard.js.
#include <emscripten.h>
#include <emscripten/stack.h>
#include <jank/gc.hpp>

extern "C" char __global_base, __data_end;
int jank_project_main(int argc, char const **argv);
extern "C" void __real_EndDrawing();

extern "C" void __wrap_EndDrawing()
{
  __real_EndDrawing();
  static size_t frames{};
  ++frames;
  EM_ASM({
    Module.jankFrameStats = ({frames: Number($0), collections: Number($1),
      heap: Number($2), used: Number($3), memory: HEAPU8.buffer.byteLength,
      time: performance.now(), suspensions: Module.jankSuspend?.count ?? 0,
      suspendedStackBytes: Module.jankSuspend?.maxBytes ?? 0});
    Module.onJankFrame?.(Module.jankFrameStats);
  }, frames, GC_get_gc_no(), GC_get_heap_size(), GC_get_heap_size() - GC_get_free_bytes());
}

int main(int argc, char const **argv)
{
  EM_ASM({ Module.jankStackBase = Number($0); }, emscripten_stack_get_base());
  GC_init();
  GC_add_roots(&__global_base, &__data_end);
  return jank_project_main(argc, argv);
}
