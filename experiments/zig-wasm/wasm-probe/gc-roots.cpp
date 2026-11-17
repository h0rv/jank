// AI-assisted tagged-reference lifetime experiment against the real runtime archive.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <jank/c_api.h>
#include <jank/error.hpp>
#include <jank/runtime/core.hpp>
#include <jank/runtime/throw.hpp>
#include <jank/runtime/obj/persistent_hash_map.hpp>
#include <jank/runtime/obj/persistent_string.hpp>
#include <jank/runtime/obj/persistent_vector.hpp>
#include <gc/gc_mark.h>

#ifdef __EMSCRIPTEN__
#include <emscripten/stack.h>
extern "C" char __global_base, __data_end;
#endif

namespace
{
  using namespace jank::runtime;
  using jank::i64;
  constexpr i64 base{ 0x100000000LL };
  constexpr size_t capacity{ 65536 };
  void **links;
  size_t used;
  object_ref registered{ _jank_null{} }, unregistered{ _jank_null{} };
  object_ref slots[128];
  size_t depth;
  bool in_runtime;
  size_t internal_collections;

  bool tagged(object_ref const value)
  {
    return (reinterpret_cast<uintptr_t>(value.raw()) >> 48) == 0xFFFA;
  }

  [[gnu::noinline]] size_t watch(object_ref const value)
  {
    if(!tagged(value) || used == capacity)
    {
      std::fprintf(stderr, "invalid tag or detector capacity exhausted\n");
      std::abort();
    }
    size_t const id{ used++ };
    void *const pointer{ detail::as_pointer(value.raw()) };
    links[id] = reinterpret_cast<void *>(GC_HIDE_POINTER(pointer));
    if(GC_general_register_disappearing_link(&links[id], pointer) != GC_SUCCESS)
    {
      std::abort();
    }
    return id;
  }

  struct shadow
  {
    size_t index{};
    explicit shadow(object_ref const value)
    {
#ifdef GC_ROOTS_SHADOW
      if(depth == 128) { std::abort(); }
      index = depth++;
      slots[index] = value;
#endif
    }
    void update(object_ref const value)
    {
#ifdef GC_ROOTS_SHADOW
      slots[index] = value;
#endif
    }
    ~shadow()
    {
#ifdef GC_ROOTS_SHADOW
      slots[--depth] = object_ref{ _jank_null{} };
#endif
    }
  };

  bool live(size_t const begin, size_t const end)
  {
    for(size_t i{ begin }; i < end; ++i)
    {
      if(links[i] == nullptr) { return false; }
    }
    return true;
  }

  [[gnu::noinline]] void churn()
  {
    for(int i{}; i < 4096; ++i)
    {
      make_box<obj::persistent_string>("discarded allocation with a nontrivial string payload");
      make_box(base + i);
    }
    GC_clear_stack(nullptr);
    GC_gcollect();
  }

  [[gnu::noinline]] object_ref fixture()
  {
    GC_disable();
    object_ref result{ make_box<obj::persistent_vector>() };
    for(int i{}; i < 128; ++i)
    {
      object_ref value{ i % 2 == 0 ? object_ref{ make_box(base + i) }
                                   : object_ref{ make_box<obj::persistent_string>("tagged payload") } };
      watch(value);
      result = conj(result, value);
    }
    watch(result);
    GC_enable();
    return result;
  }

  [[gnu::noinline]] bool verify(object_ref const value)
  {
    if(!tagged(value) || value.get_type() != object_type::persistent_vector) { return false; }
    for(int i{}; i < 128; ++i)
    {
      object_ref const item{ value.nth(make_box(i)) };
      if(!tagged(item)) { return false; }
      if(i % 2 == 0)
      {
        if(item.get_type() != object_type::integer || item.to_integer() != base + i) { return false; }
      }
      else if(item.get_type() != object_type::persistent_string || item.to_string() != "tagged payload")
      { return false; }
    }
    return true;
  }

  [[gnu::noinline]] bool check(size_t const begin, size_t const end, object_ref const value)
  {
    GC_disable();
    bool const ok{ live(begin, end) && verify(value) };
    GC_enable();
    return ok;
  }

  [[gnu::noinline]] bool locals()
  {
    size_t const begin{ used };
    object_ref const value{ fixture() };
    size_t const end{ used };
    shadow guard{ value };
    for(int round{}; round < 32; ++round)
    {
      churn();
      if(!check(begin, end, value)) { return false; }
    }
    return true;
  }

  [[gnu::noinline]] bool nested(int const level)
  {
    size_t const begin{ used };
    object_ref const value{ fixture() };
    size_t const end{ used };
    shadow guard{ value };
    bool const child{ level ? nested(level - 1) : (churn(), true) };
    return child && check(begin, end, value);
  }

  [[gnu::noinline]] bool temporary(object_ref const value, size_t const begin)
  {
    size_t const end{ used };
    shadow guard{ value };
    churn();
    return check(begin, end, value);
  }

  [[gnu::noinline]] object_ref operand_value()
  {
    object_ref const value{ fixture() };
#ifdef GC_ROOTS_SHADOW
    slots[depth++] = value;
#endif
    return value;
  }

  [[gnu::noinline]] size_t collecting_argument()
  {
    churn();
    return GC_get_gc_no();
  }

  [[gnu::noinline]] bool consume_operand(object_ref const value, size_t const token, size_t const begin)
  {
    bool const ok{ token > 0 && check(begin, used, value) };
#ifdef GC_ROOTS_SHADOW
    slots[--depth] = object_ref{ _jank_null{} };
#endif
    return ok;
  }

  [[gnu::noinline]] bool operand()
  {
    size_t const begin{ used };
    return consume_operand(operand_value(), collecting_argument(), begin);
  }

  size_t unwind_collections;
  size_t unwind_watch_begin;
  bool unwind_retained;
  bool collect_on_unwind{ true };

  struct collecting_destructor
  {
    ~collecting_destructor()
    {
      if(collect_on_unwind)
      {
        auto const before{ GC_get_gc_no() };
        churn();
        unwind_collections += GC_get_gc_no() - before;
        unwind_retained &= live(unwind_watch_begin, used);
      }
    }
  };

  [[gnu::noinline]] void unwind_frames(int const level, bool const payload)
  {
    collecting_destructor guard;
    if(level) { unwind_frames(level - 1, payload); }
    else if(payload) { jank_throw(fixture().raw()); }
    else { throw 42; }
  }

  [[gnu::noinline]] bool exception_local()
  {
    size_t const begin{ used };
    object_ref const value{ fixture() };
    size_t const end{ used };
    shadow guard{ value };
    unwind_collections = 0;
    unwind_watch_begin = begin;
    unwind_retained = true;
    try { unwind_frames(3, false); }
    catch(int const token)
    {
      churn();
      bool const ok{ token == 42 && unwind_collections >= 4 && unwind_retained && check(begin, end, value) };
      std::printf("EXCEPTION local: unwind-collections=%zu retained-during-unwind=%d\n",
                  unwind_collections, unwind_retained);
      return ok;
    }
    return false;
  }

  [[gnu::noinline]] bool exception_payload()
  {
    size_t const begin{ used };
    unwind_collections = 0;
    unwind_watch_begin = begin;
    unwind_retained = true;
    try { unwind_frames(3, true); }
    catch(object_ref const &value)
    {
      churn();
      bool const ok{ unwind_collections >= 4 && unwind_retained && check(begin, used, value) };
      std::printf(
        "EXCEPTION payload: unwind-collections=%zu retained-during-unwind=%d runtime-rooted=1\n",
        unwind_collections,
        unwind_retained);
      return ok;
    }
    return false;
  }

  [[gnu::noinline]]
  void rethrow_payload()
  {
    collecting_destructor guard;
    try
    {
      unwind_frames(3, true);
    }
    catch(object_ref const &)
    {
      churn();
      unwind_retained &= live(unwind_watch_begin, used);
      throw;
    }
  }

  [[gnu::noinline]]
  bool exception_rethrow()
  {
    size_t const begin{ used };
    unwind_collections = 0;
    unwind_watch_begin = begin;
    unwind_retained = true;
    try
    {
      rethrow_payload();
    }
    catch(object_ref const &value)
    {
      churn();
      return unwind_collections >= 5 && unwind_retained && check(begin, used, value);
    }
    return false;
  }

  [[gnu::noinline]]
  std::exception_ptr capture_payload()
  {
    try
    {
      unwind_frames(3, true);
    }
    catch(object_ref const &)
    {
      return std::current_exception();
    }
    return {};
  }

  [[gnu::noinline]]
  bool retain_exception_ptr(size_t const begin)
  {
    auto saved{ capture_payload() };
    auto copy{ saved };
    saved = {};
    churn();
    if(!unwind_retained || !live(begin, used))
    {
      return false;
    }
    try
    {
      std::rethrow_exception(copy);
    }
    catch(object_ref const &value)
    {
      churn();
      return unwind_collections >= 4 && check(begin, used, value);
    }
    return false;
  }

  [[gnu::noinline]]
  bool exception_ptr()
  {
    size_t const begin{ used };
    unwind_collections = 0;
    unwind_watch_begin = begin;
    unwind_retained = true;
    if(!retain_exception_ptr(begin))
    {
      return false;
    }
    for(int i{}; i < 32 && links[begin]; ++i)
    {
      churn();
    }
    return links[begin] == nullptr;
  }

  [[gnu::noinline]]
  void error_payload()
  {
    auto const value{ jank::make_error(jank::error::kind::runtime_uncaught_exception,
                                       jank::read::source::unknown()) };
    if(used == capacity)
    {
      std::abort();
    }
    links[used] = reinterpret_cast<void *>(GC_HIDE_POINTER(value.get()));
    if(GC_general_register_disappearing_link(&links[used++], value.get()) != GC_SUCCESS)
    {
      std::abort();
    }
    jank::throw_error(value);
  }

  [[gnu::noinline]]
  void unwind_error()
  {
    collecting_destructor guard;
    error_payload();
  }

  [[gnu::noinline]]
  std::exception_ptr capture_error()
  {
    try
    {
      unwind_error();
    }
    catch(jank::error_ref const &)
    {
      return std::current_exception();
    }
    return {};
  }

  [[gnu::noinline]]
  bool retain_error(size_t const begin)
  {
    auto saved{ capture_error() };
    churn();
    if(!unwind_retained || !live(begin, used))
    {
      return false;
    }
    try
    {
      std::rethrow_exception(saved);
    }
    catch(jank::error_ref const &value)
    {
      churn();
      return live(begin, used) && value->kind == jank::error::kind::runtime_uncaught_exception;
    }
    return false;
  }

  [[gnu::noinline]]
  bool exception_error()
  {
    size_t const begin{ used };
    unwind_collections = 0;
    unwind_watch_begin = begin;
    unwind_retained = true;
    if(!retain_error(begin))
    {
      return false;
    }
    for(int i{}; i < 32 && links[begin]; ++i)
    {
      churn();
    }
    return unwind_collections >= 1 && links[begin] == nullptr;
  }

  [[gnu::noinline]] uintptr_t stack_pointer()
  {
#ifdef __EMSCRIPTEN__
    return emscripten_stack_get_current();
#else
    return reinterpret_cast<uintptr_t>(__builtin_frame_address(0));
#endif
  }

  [[gnu::noinline]] bool exception_stack()
  {
    size_t const begin{ used };
    object_ref const value{ fixture() };
    size_t const end{ used };
    shadow guard{ value };
    auto const before{ stack_pointer() };
    unwind_collections = 0;
    unwind_watch_begin = begin;
    unwind_retained = true;
    for(int i{}; i < 10000; ++i)
    {
      collect_on_unwind = i % 1000 == 0;
      try { unwind_frames(2, false); }
      catch(int const token)
      {
        if(token != 42) { return false; }
        if(collect_on_unwind) { churn(); }
      }
      auto const after{ stack_pointer() };
      if(after != before || !live(begin, end) || !unwind_retained)
      {
        collect_on_unwind = true;
        std::printf("EXCEPTION stack: iterations=%d before=%zu after=%zu retained=%d\n",
                    i + 1, before, after, live(begin, end));
        return false;
      }
    }
    collect_on_unwind = true;
    bool const retained{ check(begin, end, value) };
    bool const recovery{ locals() && nested(3)
                         && [] { size_t const begin{ used }; return temporary(fixture(), begin); }()
                         && operand() };
    std::printf("EXCEPTION stack: iterations=10000 before=%zu after=%zu unwind-collections=%zu recovery=%d\n",
                before, stack_pointer(), unwind_collections, recovery);
    return retained && recovery && unwind_collections >= 30;
  }

  [[gnu::noinline]] bool globals(bool const register_slot)
  {
    size_t const begin{ used };
    if(register_slot) { registered = fixture(); }
    else { unregistered = fixture(); }
    size_t const end{ used };
    churn();
    bool const ok{ check(begin, end, register_slot ? registered : unregistered) };
    registered = unregistered = object_ref{ _jank_null{} };
    return ok;
  }

  void GC_CALLBACK collection(GC_EventType const event)
  {
    if(in_runtime && event == GC_EVENT_START) { ++internal_collections; }
  }

  [[gnu::noinline]] object_ref runtime_assoc(object_ref const map, object_ref const key,
                                           object_ref const value)
  {
    in_runtime = true;
    object_ref const result{ assoc(map, key, value) };
    in_runtime = false;
    return result;
  }

  [[gnu::noinline]] bool runtime_internal()
  {
    size_t const begin{ used };
    internal_collections = 0;
    object_ref map{ make_box<obj::persistent_hash_map>() };
    if(!tagged(map)) { std::abort(); }
    shadow map_guard{ map };
    GC_set_free_space_divisor(64);
    GC_set_on_collection_event(collection);
    for(int i{}; i < 8192; ++i)
    {
      GC_disable();
      object_ref const key{ make_box(base + i) };
      object_ref const value{ make_box(base * 2 + i) };
      watch(key);
      watch(value);
      shadow key_guard{ key }, value_guard{ value };
      size_t const end{ used };
      GC_enable();
      map = runtime_assoc(map, key, value);
      if(!tagged(map)) { std::abort(); }
      map_guard.update(map);
      if(!live(begin, end))
      {
        GC_set_on_collection_event(nullptr);
        GC_set_free_space_divisor(3);
        return false;
      }
    }
    GC_set_on_collection_event(nullptr);
    GC_set_free_space_divisor(3);
    if(!internal_collections) { return false; }
    GC_disable();
    bool ok{ true };
    for(int i{}; i < 8192; ++i)
    {
      object_ref const value{ map.get(make_box(base + i)) };
      if(!tagged(value) || value.get_type() != object_type::integer
         || value.to_integer() != base * 2 + i) { ok = false; break; }
    }
    GC_enable();
    return ok;
  }

  [[gnu::noinline]] size_t discarded()
  {
    return watch(make_box<obj::persistent_string>("hidden-only negative control"));
  }

  [[gnu::noinline]] bool reclaim()
  {
    size_t const id{ discarded() };
    for(int i{}; i < 32 && links[id]; ++i) { churn(); }
    return links[id] == nullptr;
  }
}

int main(int argc, char **argv)
{
  GC_INIT();
#ifdef __EMSCRIPTEN__
  if(argc > 1 && std::strcmp(argv[1], "static-roots") == 0)
  { GC_add_roots(&__global_base, &__data_end); }
#endif
  jank_init_base();
  links = static_cast<void **>(GC_MALLOC_ATOMIC(capacity * sizeof(void *)));
  GC_add_roots(&links, &links + 1);
  GC_add_roots(&registered, &registered + 1);
#ifdef GC_ROOTS_SHADOW
  GC_add_roots(slots, slots + 128);
#endif
  struct test { char const *name; bool (*run)();
  };

  test const tests[]{
    {              "locals",locals                            },
    {              "nested",     [] { return nested(31); } },
    {           "temporary",
     [] {
     size_t const begin{ used };
     return temporary(fixture(), begin);
     }                                                    },
    {             "operand",                       operand },
    {     "exception-local",               exception_local },
    {   "exception-payload",             exception_payload },
    {     "exception-stack",               exception_stack },
    {   "exception-rethrow",             exception_rethrow },
    {       "exception-ptr",                 exception_ptr },
    {     "exception-error",               exception_error },
    {    "runtime-internal",              runtime_internal },
    {   "registered-global",  [] { return globals(true); } },
    { "unregistered-global", [] { return globals(false); } },
    {     "reclaim-control",                       reclaim }
  };
  int passed{}, failed{};
  for(auto const &test : tests)
  {
    if(argc > 2 && std::strcmp(argv[2], test.name) != 0) { continue; }
    auto const before{ GC_get_gc_no() };
    bool const retained{ test.run() };
    auto const collections{ GC_get_gc_no() - before };
    bool const ok{ retained && collections > 0 };
    std::printf("CASE %s: %s collections=%zu internal-collections=%zu\n", test.name,
                ok ? "PASS" : "FAIL", static_cast<size_t>(collections),
                std::strcmp(test.name, "runtime-internal") == 0 ? internal_collections : 0);
    std::fflush(stdout);
    ok ? ++passed : ++failed;
  }
  std::printf("GC ROOTS: %d passed, %d failed\n", passed, failed);
  return failed ? 1 : 0;
}
