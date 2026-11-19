// AI-assisted lifetime probe. No static registration or local spilling.
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>

#include <gc/gc.h>

namespace
{
  void **weak_link;
  bool wrapped;
  unsigned destructions;
  // Instrument the actual frees; the collector does not scan Wasm statics here.
  void *live_blocks[2];

  constexpr auto pointer_mask = static_cast<std::uintptr_t>(0x0000'FFFF'FFFF'FFFFull);
  constexpr auto pointer_tag = static_cast<std::uintptr_t>(0xFFFA'0000'0000'0000ull);

  void require(bool ok, char const *message)
  {
    if(!ok)
    {
      std::fprintf(stderr, "FAIL: %s\n", message);
      std::exit(1);
    }
  }

  void check_during_collection(char const *stage)
  {
    auto const before = GC_get_gc_no();
    GC_gcollect();
    require(GC_get_gc_no() > before, "collection did not run");
    require((*weak_link != nullptr) == wrapped, stage);
  }

  [[gnu::noinline]] std::uintptr_t make_word(bool tagged)
  {
    GC_disable();
    auto const value = static_cast<int *>(GC_malloc_atomic(sizeof(int)));
    require(value != nullptr, "payload allocation");
    *value = 42;
    *weak_link = value;
    require(GC_general_register_disappearing_link(weak_link, value) == GC_SUCCESS,
            "weak link registration");
    GC_enable();
    return reinterpret_cast<std::uintptr_t>(value) | (tagged ? pointer_tag : 0);
  }

  struct alignas(__BIGGEST_ALIGNMENT__) carrying
  {
    std::uintptr_t word;

    ~carrying()
    {
      check_during_collection("payload lifetime in exception destructor");
      ++destructions;
    }
  };

  [[gnu::noinline]] void throw_payload(bool tagged)
  {
    struct collect_on_unwind
    {
      ~collect_on_unwind() { check_during_collection("payload lifetime on unwind"); }
    } guard;
    throw carrying{ make_word(tagged) };
  }

  void check_catch(carrying const &exception, bool tagged)
  {
    require(reinterpret_cast<std::uintptr_t>(&exception) % alignof(carrying) == 0,
            "exception payload alignment");
    require((GC_base_C(&exception) != nullptr) == wrapped, "Boehm owns the exception block");
    check_during_collection("payload lifetime in catch");
    if(wrapped)
    {
      auto const address = tagged ? exception.word & pointer_mask : exception.word;
      auto const payload = reinterpret_cast<int const *>(address);
      require(payload == *weak_link && *payload == 42, "caught payload contents");
    }
  }

  void check_payload(bool tagged)
  {
    auto const before = destructions;
    std::exception_ptr retained;
    try
    {
      throw_payload(tagged);
    }
    catch(carrying const &exception)
    {
      check_catch(exception, tagged);
      retained = std::current_exception();
    }
    auto last_owner = retained;
    retained = nullptr;
    check_during_collection("payload lifetime through a copied exception_ptr");
    require(destructions == before, "exception destroyed before last owner");
    try
    {
      std::rethrow_exception(last_owner);
    }
    catch(carrying const &exception)
    {
      check_catch(exception, tagged);
    }
    last_owner = nullptr;
    require(destructions == before + 1, "exception not destroyed by last owner");
    require(!live_blocks[0] && !live_blocks[1], "exception block was not freed");
    GC_gcollect();
    require(*weak_link == nullptr, "payload still rooted after exception free");
  }

  struct broken
  {
    [[gnu::noinline]] broken()
    {
      require((live_blocks[0] != nullptr) == wrapped, "exception storage before construction");
      throw 7;
    }
  };
}

extern "C" void *__real_GC_malloc_uncollectable(std::size_t);
extern "C" void __real_GC_free(void *);

extern "C" void *__wrap_GC_malloc_uncollectable(std::size_t size)
{
  auto const block = __real_GC_malloc_uncollectable(size);
  require(block != nullptr, "exception allocation");
  for(auto &live : live_blocks)
  {
    if(!live)
    {
      live = block;
      return block;
    }
  }
  require(false, "too many live exception blocks");
  return block;
}

extern "C" void __wrap_GC_free(void *block)
{
  for(auto &live : live_blocks)
  {
    if(live == block)
    {
      live = nullptr;
    }
  }
  __real_GC_free(block);
}

int main(int argc, char **argv)
{
  require(argc == 2, "expected wrapped or control");
  wrapped = std::strcmp(argv[1], "wrapped") == 0;
  GC_INIT();
  GC_set_free_space_divisor(1);
  weak_link = static_cast<void **>(GC_malloc_atomic_uncollectable(sizeof(void *)));
  require(weak_link != nullptr, "weak link allocation");
  check_payload(false);
  if(sizeof(void *) == 8)
  {
    check_payload(true);
  }
  try
  {
    throw broken{};
  }
  catch(int value)
  {
    require(value == 7, "throw during exception construction");
  }
  require(!live_blocks[0] && !live_blocks[1], "constructor failure leaked exception storage");
  GC_free(weak_link);
  std::printf("PASS: wasm%zu exception roots (%s)\n", sizeof(void *) * 8, argv[1]);
}
