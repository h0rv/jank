#ifndef __EMSCRIPTEN__
  #include <cpptrace/basic.hpp>
#endif

#include <jtl/assert.hpp>
#include <jank/util/fmt/print.hpp>

namespace jtl
{
  void do_assertion_panic(immutable_string_view const &msg)
  {
    jank::util::println(stderr, "{}", msg);
#ifdef __EMSCRIPTEN__
    jank::util::println(stderr, "Stack traces are unsupported on Emscripten.");
#else
    cpptrace::generate_trace().print();
#endif
    ::abort();
  }

  void do_assertion_throw(immutable_string_view const &msg)
  {
    throw std::runtime_error{ std::string{ msg } };
  }
}
