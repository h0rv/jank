// AI-assisted AOT fixture driver. The test bodies execute only in Wasm.
#include <cstdio>
#include <string_view>

#include <jank/error.hpp>
#include <jank/runtime/core/equal.hpp>
#include <jank/runtime/obj/keyword.hpp>
#include <jank/runtime/obj/persistent_hash_map.hpp>
#include <jank/runtime/obj/persistent_string.hpp>

#include "wasm-test-gc.hpp"

struct fixture
{
  char const *id;
  char const *path;
  char const *entry;
  char expected;
  void (*load)();
};

#include "wasm-fixtures.inc"

namespace
{
  using namespace jank;
  using namespace jank::runtime;

  char const *run(fixture const &test)
  {
    auto const success{ __rt_ctx->intern_keyword("success").expect_ok() };
    bool entered{};
    try
    {
      __rt_ctx->remove_ns(make_box<obj::symbol>("user"));
      context::binding_scope const bindings{ obj::persistent_hash_map::create_unique(
        std::make_pair(__rt_ctx->current_file_var, make_box<obj::persistent_string>(test.path))) };
      test.load();
      auto const entry{ __rt_ctx->find_var("user", test.entry) };
      if(entry.is_nil())
      {
        return "missing-entry";
      }
      entered = true;
      auto const result{ entry->deref().call() };
      if(test.expected != 'p' || !equal(result, success))
      {
        std::fprintf(stderr, "Unexpected result: %s\n", result.to_code_string().c_str());
        return "unexpected-result";
      }
      return "pass";
    }
    catch(obj::keyword_ref const value)
    {
      return entered && test.expected == 't' && equal(value.erase(), success) ? "pass"
                                                                            : "unexpected-throw";
    }
    catch(object_ref const value)
    {
      if(entered && test.expected != 'p' && equal(value, success) == (test.expected == 't'))
      {
        return "pass";
      }
      std::fprintf(stderr, "Unexpected throw: %s\n", value.to_code_string().c_str());
      return "unexpected-throw";
    }
    catch(error_ref const error)
    {
      std::fprintf(stderr, "%s\n", error->message.c_str());
      if(error->kind == error::kind::runtime_static_feature_disabled
         || error->kind == error::kind::runtime_module_not_found)
      {
        return "static-runtime-unsupported";
      }
      if(error::is_internal_failure_kind(error->kind))
      {
        return "internal-error";
      }
      return entered && test.expected == 'f' && error->source != read::source::unknown()
        ? "pass"
        : "jank-error";
    }
    catch(std::exception const &error)
    {
      std::fprintf(stderr, "%s\n", error.what());
      return entered && test.expected == 'f' ? "pass" : "native-exception";
    }
    catch(...)
    {
      return entered && test.expected == 'f' ? "pass" : "unexpected-throw";
    }
  }
}

int main(int const argc, char **argv)
{
  wasm_test::initialize();
  size_t index{};
  for(auto const &test : fixtures)
  {
    if(argc > 1 && std::string_view{ test.id } < argv[1])
    {
      continue;
    }
    std::printf("JANK_WASM_START %s\n", test.id);
    std::fflush(stdout);
    auto const before{ GC_get_gc_no() };
    wasm_test::collect_periodically(index++);
    auto const forced{ GC_get_gc_no() - before };
    auto const result{ run(test) };
    std::printf("\nJANK_WASM_RESULT %s %s %zu %zu %d\n",
                test.id,
                result,
                static_cast<size_t>(GC_get_gc_no() - before),
                static_cast<size_t>(forced),
                GC_is_disabled());
    std::fflush(stdout);
  }
}
