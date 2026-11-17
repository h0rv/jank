// AI-assisted tests of the target runtime's explicit capability boundaries.
#include <cstdio>
#include <stdexcept>
#include <string_view>

#include <jank/error.hpp>
#include <jank/runtime/core.hpp>
#include <jank/runtime/obj/future.hpp>
#include <jank/util/environment.hpp>
#include <jank/util/try.hpp>

int main()
{
  using namespace jank;
  auto const invoke = [](auto f) {
    int handler{};
    util::try_catch(f,
                    [&](std::exception const &) { handler = 1; },
                    [&](runtime::object_ref) { handler = 2; },
                    [&](error_ref) { handler = 3; },
                    [&]() { handler = 4; });
    return handler;
  };
  if(invoke([] {}) != 0 || invoke([] { throw std::runtime_error{ "test" }; }) != 1
     || invoke([] { throw runtime::object_ref{}; }) != 2
     || invoke([] { throw make_error(error::kind::runtime_uncaught_exception,
                                     read::source::unknown()); }) != 3
     || invoke([] { throw 42; }) != 4)
  {
    return 1;
  }
  try
  {
    util::process_path();
    return 2;
  }
  catch(std::runtime_error const &e)
  {
    if(std::string_view{ e.what() } != "Executable paths are unavailable on Emscripten")
    {
      return 3;
    }
  }
  auto const requires_threads = [](auto f) {
    try
    {
      f();
    }
    catch(std::runtime_error const &e)
    {
      return std::string_view{ e.what() } == "Futures require a thread-enabled runtime";
    }
    return false;
  };
  if(!requires_threads([] { runtime::future(runtime::object_ref{}); })
     || !requires_threads([] { runtime::cancel_future(runtime::obj::future_ref{}); })
     || !requires_threads([] { runtime::is_future_cancelled(runtime::obj::future_ref{}); }))
  {
    return 4;
  }
  util::print_exception(std::runtime_error{ "runtime smoke exception" });
  std::printf("wasm%zu runtime: exception dispatch and unsupported capabilities passed\n",
              sizeof(void *) * 8);
}
