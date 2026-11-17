// AI-assisted controls; disabling GC is diagnostic only, never a runtime fix.
#include <cstdio>
#include <cstring>
#include <jank/gc.hpp>

int jank_spike_main(int argc, char const **argv);
int jank_assertion_main(int argc, char const **argv);

#ifdef __EMSCRIPTEN__
extern "C" char __global_base, __data_end;
#endif

int main(int argc, char const **argv)
{
  if(argc > 1 && std::strcmp(argv[1], "no-gc") == 0)
  {
    GC_disable();
  }
#ifdef __EMSCRIPTEN__
  else if(argc > 1 && std::strcmp(argv[1], "static-roots") == 0)
  {
    GC_init();
    GC_add_roots(&__global_base, &__data_end);
  }
#endif
  int const status{ argc > 2 && std::strcmp(argv[2], "assertion") == 0
                      ? jank_assertion_main(argc, argv)
                      : jank_spike_main(argc, argv) };
  std::printf("startup diagnostic: exit=%d collections=%zu gc-disabled=%d\n", status,
              static_cast<size_t>(GC_get_gc_no()), GC_is_disabled());
  return status;
}
