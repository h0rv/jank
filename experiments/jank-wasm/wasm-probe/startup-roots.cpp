// AI-assisted differential diagnostic, not a production rooting strategy.
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <jank/c_api.h>
#include <jank/runtime/core.hpp>
#include <jank/runtime/obj/persistent_array_map.hpp>
#include <jank/runtime/obj/persistent_list.hpp>
#include <gc/gc_mark.h>

namespace
{
  void *volatile tagged_root;

  [[gnu::noinline]] void allocate_root()
  {
    using namespace jank::runtime;
    tagged_root = obj::persistent_array_map::create_unique(make_box(1), make_box(2)).erase().raw();
  }
}

int main(int argc, char **argv)
{
  using namespace jank::runtime;
  jank_init_base();
  bool const registered{ argc == 2 && std::strcmp(argv[1], "registered") == 0 };
  if(registered)
  {
    GC_add_roots(const_cast<void **>(&tagged_root),
                 reinterpret_cast<char *>(const_cast<void **>(&tagged_root)) + sizeof(tagged_root));
  }
  allocate_root();
  auto const before{ GC_get_gc_no() };
  GC_gcollect();
  int const marked{ GC_is_marked(jank::runtime::detail::as_pointer(tagged_root)) };
  for(int round{}; round < 8; ++round)
  {
    GC_gcollect();
    for(int i{}; i < 4096; ++i)
    {
      obj::persistent_array_map::create_unique(make_box(i), make_box(i + 1));
    }
  }
  object_ref const root{ reinterpret_cast<object *>(tagged_root) };
  auto const type{ marked ? root.get_type() : object_type::nil };
  bool const retained{ marked && type == object_type::persistent_array_map
                       && root.get(make_box(1)) == make_box(2) };
  std::printf("roots=%s collections=%zu marked=%d type=%s retained=%d map-size=%zu list-size=%zu object-size=%zu\n",
              registered ? "registered" : "default", static_cast<size_t>(GC_get_gc_no() - before),
              marked, marked ? object_type_str(type) : "unmarked", retained, sizeof(obj::persistent_array_map),
              sizeof(obj::persistent_list), sizeof(object));
  std::printf("map-align=%zu list-align=%zu object-align=%zu type-offset=%zu map-data-offset=%zu mask=%llx\n",
              alignof(obj::persistent_array_map), alignof(obj::persistent_list), alignof(object),
              offsetof(object, type), offsetof(obj::persistent_array_map, data),
              static_cast<unsigned long long>(POINTER_MASK));
  return retained ? 0 : 1;
}
