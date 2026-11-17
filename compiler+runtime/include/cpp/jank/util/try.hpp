#pragma once

#include <exception>

#if !defined(__EMSCRIPTEN__) && !defined(__wasi__)
  #include <cpptrace/from_current.hpp>
#endif

#include <jank/runtime/object.hpp>

namespace jank
{
  namespace error
  {
    struct base;
  }

  using error_ref = jtl::ref<error::base>;
}

namespace jank::util
{
  void print_exception(std::exception const &e);
  void print_exception(runtime::object_ref const e);
  void print_exception(error_ref e);
  void print_current_exception();

#if !defined(__EMSCRIPTEN__) && !defined(__wasi__)
  using cpptrace::try_catch;
  cpptrace::stacktrace resolve(cpptrace::raw_trace const &trace);
#else
  template <typename F, typename Standard, typename Object, typename Error, typename Unknown>
  void try_catch(F &&f, Standard &&standard, Object &&object, Error &&error, Unknown &&unknown)
  {
    try
    {
      f();
    }
    catch(std::exception const &e)
    {
      standard(e);
    }
    catch(runtime::object_ref const e)
    {
      object(e);
    }
    catch(error_ref const e)
    {
      error(e);
    }
    catch(...)
    {
      unknown();
    }
  }
#endif
}
