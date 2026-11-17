// AI-assisted controls; these modes are experiments, not production rooting fixes.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <jank/c_api.h>
#include <jank/gc.hpp>
#include <jank/runtime/core.hpp>
#include <jank/runtime/obj/persistent_string.hpp>

int jank_spike_main(int argc, char const **argv);
#ifndef JANK_STARTUP_SPIKE_ONLY
int jank_assertion_main(int argc, char const **argv);
#endif

#ifdef __EMSCRIPTEN__
extern "C" char __global_base, __data_end;
#endif

namespace
{
  void memory(char const *const phase)
  {
    auto const heap{ GC_get_heap_size() };
    auto const free{ GC_get_free_bytes() };
    std::printf("startup memory: phase=%s collections=%zu heap-bytes=%zu free-bytes=%zu used-bytes=%zu gc-disabled=%d\n",
                phase, static_cast<size_t>(GC_get_gc_no()), heap, free, heap - free, GC_is_disabled());
    std::fflush(stdout);
  }

  void safepoint(char const *const phase)
  {
    std::printf("startup safepoint: %s\n", phase);
    memory("before-collection");
    GC_enable();
    GC_gcollect();
    GC_disable();
    memory("after-collection");
  }

  [[gnu::noinline]] void reenter()
  {
    jank_call0(jank_deref(jank_var_intern_c("spike.core", "-main")));
  }

  [[gnu::noinline]] void churn()
  {
    for(jank::i64 i{}; i < 65536; ++i)
    {
      jank::runtime::make_box(0x100000000LL + i);
      jank::runtime::make_box<jank::runtime::obj::persistent_string>(
        "discarded safepoint churn allocation: overwrite reclaimed runtime storage before re-entry");
    }
  }
}

int main(int argc, char const **argv)
{
  bool const with_churn{ argc > 1 && std::strcmp(argv[1], "safepoint-churn") == 0 };
  bool const collect_at_safepoints{ with_churn || (argc > 1 && std::strcmp(argv[1], "safepoint") == 0) };
  bool const continuous{ argc > 1 && std::strcmp(argv[1], "continuous") == 0 };
  bool const no_gc_reentry{ argc > 1 && std::strcmp(argv[1], "no-gc-reentry") == 0 };
  bool const repeated{ collect_at_safepoints || continuous || no_gc_reentry };
  char const *const prefix{ collect_at_safepoints ? "SAFEPOINT" : "STARTUP" };
  long iterations{ 20 };
  if(repeated && argc > 2)
  {
    char *end{};
    iterations = std::strtol(argv[2], &end, 10);
    if(!*argv[2] || *end || iterations < 1 || iterations > 10000)
    {
      std::fprintf(stderr, "startup iterations must be an integer in [1, 10000]\n");
      return 2;
    }
  }
  if(no_gc_reentry || (argc > 1 && std::strcmp(argv[1], "no-gc") == 0))
  {
    GC_disable();
  }
#ifdef __EMSCRIPTEN__
  else if(collect_at_safepoints || continuous || (argc > 1 && std::strcmp(argv[1], "static-roots") == 0))
  {
    GC_init();
    GC_add_roots(&__global_base, &__data_end);
  }
#endif
  if(collect_at_safepoints)
  {
    GC_init();
    GC_disable();
    safepoint("before-spike");
  }
  memory("before-spike");
  if(repeated)
  {
    int status{};
    for(long iteration{ 1 }; iteration <= iterations; ++iteration)
    {
      std::printf("%s BEGIN: iteration=%ld/%ld\n", prefix, iteration, iterations);
      std::fflush(stdout);
      if(iteration == 1) { status = jank_spike_main(argc, argv); }
      else { reenter(); }
      if(collect_at_safepoints) { safepoint("after-entry"); }
      if(with_churn)
      {
        churn();
        safepoint("after-churn");
      }
      std::printf("%s ITERATION %ld/%ld: collections=%zu used-bytes=%zu heap-bytes=%zu status=%d\n",
                  prefix, iteration, iterations, static_cast<size_t>(GC_get_gc_no()),
                  GC_get_heap_size() - GC_get_free_bytes(), GC_get_heap_size(), status);
      std::fflush(stdout);
      if(status) { return status; }
    }
    std::printf("startup diagnostic: exit=%d collections=%zu gc-disabled=%d\n", status,
                static_cast<size_t>(GC_get_gc_no()), GC_is_disabled());
    return status;
  }
#ifndef JANK_STARTUP_SPIKE_ONLY
  int const status{ argc > 2 && std::strcmp(argv[2], "assertion") == 0
                      ? jank_assertion_main(argc, argv)
                      : jank_spike_main(argc, argv) };
#else
  int const status{ jank_spike_main(argc, argv) };
#endif
  memory("after-spike");
  std::printf("startup diagnostic: exit=%d collections=%zu gc-disabled=%d\n", status,
              static_cast<size_t>(GC_get_gc_no()), GC_is_disabled());
  return status;
}
