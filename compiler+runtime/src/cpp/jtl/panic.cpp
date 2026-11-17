#if !defined(__EMSCRIPTEN__) && !defined(__wasi__)
  #include <cpptrace/basic.hpp>
#endif

#include <jtl/panic.hpp>
#include <jank/util/fmt/print.hpp>

namespace jtl::detail
{
  [[noreturn]]
  void panic(char const * const msg)
  {
    jank::util::println(stderr, "Panic encountered: {}", msg);
#ifdef __EMSCRIPTEN__
    jank::util::println(stderr, "Stack traces are unsupported on Emscripten.");
#elif defined(__wasi__)
    jank::util::println(stderr, "Stack traces are unsupported on WASI.");
#else
    cpptrace::generate_trace().print();
#endif
    ::abort();
  }
}
