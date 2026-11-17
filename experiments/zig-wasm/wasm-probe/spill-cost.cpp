// AI-assisted measurement driver, not a GC rooting fix.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <unistd.h>
#include <jank/c_api.h>
#include <jank/gc.hpp>

int jank_spike_main(int, char const **);
#ifdef __EMSCRIPTEN__
extern "C" char __global_base, __data_end;
#endif

int main(int argc, char const **argv)
{
  GC_init();
#ifdef __EMSCRIPTEN__
  GC_add_roots(&__global_base, &__data_end);
#endif
  if(argc > 1 && std::strcmp(argv[1], "no-gc") == 0) { GC_disable(); }
  GC_start_performance_measurement();
  auto const init_collections{ GC_get_gc_no() };
  auto const init_gc_ms{ GC_get_full_gc_total_time() };
  auto const init_start{ std::chrono::steady_clock::now() };
  if(jank_spike_main(argc, argv)) { return 1; }
  auto const init_end{ std::chrono::steady_clock::now() };
  std::printf("FIRST_ENTRY ms=%.6f\n",
    std::chrono::duration<double, std::milli>(init_end - init_start).count());
  std::printf("FIRST_ENTRY_GC collections=%zu ms=%lu\n",
    static_cast<size_t>(GC_get_gc_no() - init_collections),
    GC_get_full_gc_total_time() - init_gc_ms);
  auto call = [] { jank_call0(jank_deref(jank_var_intern_c("spike.core", "-main"))); };
  std::fflush(stdout);
  int const saved{ dup(STDOUT_FILENO) };
  if(saved < 0 || !std::freopen("/dev/null", "w", stdout)) { return 2; }
  for(int i{}; i < 1000; ++i) { call(); }
  auto const before{ GC_get_gc_no() };
  auto const start{ std::chrono::steady_clock::now() };
  for(int i{}; i < 10000; ++i) { call(); }
  std::fflush(stdout);
  auto const end{ std::chrono::steady_clock::now() };
  auto const after{ GC_get_gc_no() };
  if(dup2(saved, STDOUT_FILENO) < 0) { return 2; }
  close(saved);
  call();
  std::printf("COST ns-per-call=%.3f collections-before=%zu collections-after=%zu gc-disabled=%d\n",
    std::chrono::duration<double, std::nano>(end - start).count() / 10000,
    static_cast<size_t>(before), static_cast<size_t>(after), GC_is_disabled());
}
