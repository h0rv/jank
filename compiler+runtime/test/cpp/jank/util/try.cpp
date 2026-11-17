#include <jank/error.hpp>
#include <jank/util/try.hpp>

/* This must go last; doctest and glog both define CHECK and family. */
#include <doctest/doctest.h>

namespace jank::util
{
  TEST_CASE("util::try_catch dispatches exceptions without changing normal returns")
  {
    auto const invoke = [](auto f) {
      int handler{};
      util::try_catch(f,
                      [&](std::exception const &) { handler = 1; },
                      [&](runtime::object_ref) { handler = 2; },
                      [&](error_ref) { handler = 3; },
                      [&]() { handler = 4; });
      return handler;
    };
    CHECK_EQ(invoke([] {}), 0);
    CHECK_EQ(invoke([] { throw std::runtime_error{ "test" }; }), 1);
    CHECK_EQ(invoke([] { runtime::throw_object(runtime::object_ref{}); }), 2);
    CHECK_EQ(invoke([] {
               throw_error(
                 make_error(error::kind::runtime_uncaught_exception, read::source::unknown()));
             }),
             3);
    CHECK_EQ(invoke([] { throw 42; }), 4);
  }
}
