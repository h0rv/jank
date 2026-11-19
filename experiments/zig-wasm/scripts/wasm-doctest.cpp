// AI-assisted runner for the unmodified jank doctest sources.
#include <cstdio>

#include "wasm-test-gc.hpp"

#define DOCTEST_CONFIG_IMPLEMENT
#include <doctest/doctest.h>

struct collection_listener : doctest::IReporter
{
  explicit collection_listener(doctest::ContextOptions const &) {}

  void test_case_start(doctest::TestCaseData const &test) override
  {
    current = &test;
    auto const before{ GC_get_gc_no() };
    wasm_test::collect_periodically(index++);
    forced_collections += GC_get_gc_no() - before;
  }

  void report_query(doctest::QueryData const &) override {}
  void test_run_start() override {}
  void test_run_end(doctest::TestRunStats const &stats) override
  {
    std::printf("JANK_WASM_DOCTEST %u %u %u %zu\n",
                stats.numTestCases,
                stats.numTestCasesPassingFilters,
                stats.numTestCasesFailed,
                forced_collections);
  }
  void test_case_reenter(doctest::TestCaseData const &) override {}
  void test_case_end(doctest::CurrentTestCaseStats const &stats) override
  {
    if(!stats.testCaseSuccess)
    {
      std::printf("JANK_WASM_DOCTEST_FAILURE %d %s:%u %s\n",
                  stats.failure_flags,
                  current->m_file.c_str(),
                  current->m_line,
                  current->m_name);
    }
  }
  void test_case_exception(doctest::TestCaseException const &) override {}
  void subcase_start(doctest::SubcaseSignature const &) override {}
  void subcase_end() override {}
  void log_assert(doctest::AssertData const &) override {}
  void log_message(doctest::MessageData const &) override {}
  void test_case_skipped(doctest::TestCaseData const &) override {}

  size_t index{};
  size_t forced_collections{};
  doctest::TestCaseData const *current{};
};

DOCTEST_REGISTER_LISTENER("gc-pressure", 0, collection_listener);

int main(int const argc, char const **argv)
{
  auto const before{ GC_get_gc_no() };
  wasm_test::initialize();
  jank::runtime::__rt_ctx->in_ns_var->deref().call(
    jank::runtime::make_box<jank::runtime::obj::symbol>("user"));
  jank::runtime::__rt_ctx->intern_var("clojure.core", "refer")
    .expect_ok()
    .call(jank::runtime::make_box<jank::runtime::obj::symbol>("clojure.core"));

  doctest::Context context;
  context.applyCommandLine(argc, argv);
  context.setOption("no-breaks", true);
  auto const status{ context.run() };
  std::printf("JANK_WASM_DOCTEST_GC %zu %zu %d\n",
              static_cast<size_t>(before),
              static_cast<size_t>(GC_get_gc_no()),
              GC_is_disabled());
  return status;
}
