// AI-assisted measurement-only launcher; no benchmark kernels live here.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <jank/gc.hpp>
int bench_entry(int, char const **);
#ifdef __EMSCRIPTEN__
extern "C" char __global_base, __data_end;
#endif
int main(int argc, char const **argv)
{
  GC_init();
#ifdef __EMSCRIPTEN__
  GC_add_roots(&__global_base, &__data_end);
#endif
  if(argc > 1 && std::strcmp(argv[1], "unsafe-no-gc") == 0) { GC_disable(); }
  auto const start = std::chrono::steady_clock::now();
  std::printf("INIT clock-ms=%.6f\n",
    std::chrono::duration<double, std::milli>(start.time_since_epoch()).count());
  int const status = bench_entry(argc, argv);
  std::printf("FIRST_ENTRY ms=%.6f gc-disabled=%d\n",
    std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count(),
    GC_is_disabled());
  return status;
}
