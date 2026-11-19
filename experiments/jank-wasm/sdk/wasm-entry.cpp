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
#ifdef JANK_WASM_BETWEEN_FRAME_GC
  // Disable automatic collections before ordinary C++ static initialization.
  __attribute__((constructor(101))) void disable_early_gc()
  {
    GC_disable();
    GC_set_finalize_on_demand(1);
  }
#else
  size_t frames{};
#endif

  [[gnu::noinline]] void invoke_frame()
  {
    jank_call0(jank_deref(jank_var_intern_c(jank_wasm_frame_ns, jank_wasm_frame_var)));
  }

  void collect()
  {
    GC_enable();
    GC_gcollect();
    GC_disable();
#ifdef JANK_WASM_BETWEEN_FRAME_GC
    GC_invoke_finalizers();
#endif
  }

  void publish_stats(size_t frame_count, int interval)
  {
    EM_ASM({
      Module.jankFrameStats = ({frames: Number($0), collections: Number($1),
        heap: Number($2), used: Number($3), memory: HEAPU8.buffer.byteLength,
        time: performance.now(), collectEvery: $4});
      Module.onJankFrame?.(Module.jankFrameStats);
    }, frame_count, GC_get_gc_no(), GC_get_heap_size(),
       GC_get_heap_size() - GC_get_free_bytes(), interval);
  }

#ifndef JANK_WASM_BETWEEN_FRAME_GC
  void frame()
  {
    invoke_frame();
    ++frames;
    int const interval{ EM_ASM_INT({
      const n = Module.jankCollectEvery ?? 1;
      return Number.isInteger(n) && n >= 1 && n <= 60 ? n : 1;
    }) };
    if(frames % interval == 0) { collect(); }
    publish_stats(frames, interval);
  }
#endif
}

#ifdef JANK_WASM_BETWEEN_FRAME_GC
extern "C"
{
  EMSCRIPTEN_KEEPALIVE void jank_wasm_tick() { invoke_frame(); }
  EMSCRIPTEN_KEEPALIVE void jank_wasm_collect() { collect(); }
  EMSCRIPTEN_KEEPALIVE void jank_wasm_publish(int frames, int interval)
  {
    publish_stats(frames, interval);
  }
}

EM_JS(void, schedule_frames, (), {
  let frames = 0;
  function next() {
    // Enter Wasm separately for collection, after main or the last frame returned.
    if (frames === 0) Module['_jank_wasm_collect']();
    Module['_jank_wasm_tick']();
    ++frames;
    const n = Module['jankCollectEvery'] ?? 30;
    const interval = Number.isInteger(n) && n >= 1 && n <= 60 ? n : 1;
    if (frames % interval === 0) Module['_jank_wasm_collect']();
    Module['_jank_wasm_publish'](frames, interval);
    requestAnimationFrame(next);
  }
  requestAnimationFrame(next);
});
#endif

int main(int argc, char const **argv)
{
  GC_init();
  jank_wasm_register_roots();
#ifndef JANK_WASM_BETWEEN_FRAME_GC
  GC_disable();
#endif
  int const status{ jank_project_main(argc, argv) };
  if(status) { return status; }
#ifdef JANK_WASM_BETWEEN_FRAME_GC
  schedule_frames();
#else
  collect();
  if(jank_wasm_frame_var) { emscripten_set_main_loop(frame, 0, 0); }
#endif
  return 0;
}
