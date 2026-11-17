// AI-assisted tagged-reference lifetime experiment against the real runtime archive.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <jank/c_api.h>
#include <jank/runtime/core.hpp>
#include <jank/runtime/obj/persistent_hash_map.hpp>
#include <jank/runtime/obj/persistent_string.hpp>
#include <jank/runtime/obj/persistent_vector.hpp>
#include <gc/gc_mark.h>

#ifdef __EMSCRIPTEN__
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
  struct test { char const *name; bool (*run)(); };
  test const tests[]{ { "locals", locals }, { "nested", [] { return nested(31); } },
                      { "temporary", [] { size_t const begin{ used }; return temporary(fixture(), begin); } },
                      { "runtime-internal", runtime_internal },
                      { "registered-global", [] { return globals(true); } },
                      { "unregistered-global", [] { return globals(false); } },
                      { "reclaim-control", reclaim } };
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
