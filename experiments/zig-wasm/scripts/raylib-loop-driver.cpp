// AI-assisted host adapter for an unchanged synchronous raylib application.
#include <emscripten.h>
#include <jank/gc.hpp>

int jank_project_main(int argc, char const **argv);
extern "C" void jank_wasm_register_roots();
extern "C" void __real_EndDrawing();

extern "C" void __wrap_EndDrawing()
{
  __real_EndDrawing();
  static size_t frames{};
  ++frames;
  EM_ASM({
    Module.jankFrameStats = ({frames: Number($0), collections: Number($1),
      heap: Number($2), used: Number($3), memory: HEAPU8.buffer.byteLength,
      time: performance.now()});
    Module.onJankFrame?.(Module.jankFrameStats);
  }, frames, GC_get_gc_no(), GC_get_heap_size(), GC_get_heap_size() - GC_get_free_bytes());
}

int main(int argc, char const **argv)
{
  GC_init();
  jank_wasm_register_roots();
  return jank_project_main(argc, argv);
}
