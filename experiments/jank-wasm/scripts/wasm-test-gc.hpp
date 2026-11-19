// AI-assisted test driver for the experimental Emscripten runtime.
#pragma once

#include <jank/c_api.h>
#include <jank/gc.hpp>
#include <jank/runtime/context.hpp>

extern "C" char __global_base, __data_end;
extern "C" void jank_load_clojure_core();
extern "C" void jank_load_clojure_string();
extern "C" void jank_load_clojure_walk();

namespace wasm_test
{
  inline void initialize()
  {
    GC_set_free_space_divisor(1);
    GC_init();
    GC_add_roots(&__global_base, &__data_end);
    jank_init_base();
    jank::runtime::__rt_ctx = new(UseGC) jank::runtime::context{};
    jank_load_clojure_core();
    jank_module_register("clojure.string", &jank_load_clojure_string);
    jank_module_register("clojure.walk", &jank_load_clojure_walk);
  }

  inline void collect_periodically(size_t const index)
  {
    if(index % 8 == 0)
    {
      GC_gcollect();
    }
  }
}
