// Match the libc++abi header shipped with the Emscripten compiler doing the link.
#define _LIBCPP_ENABLE_CXX17_REMOVED_UNEXPECTED_FUNCTIONS
#include "cxa_exception.h"

#include <cstddef>
#include <exception>
#include <limits>
#include <memory>

#include <gc/gc.h>

namespace
{
  // libc++abi uses the compiler's maximum useful alignment, not max_align_t.
  struct [[gnu::aligned]] abi_alignment {};
  constexpr auto alignment = alignof(abi_alignment);
  constexpr auto header_size = sizeof(__cxxabiv1::__cxa_exception);
  constexpr auto header_span = (header_size + alignment - 1) / alignment * alignment;
  constexpr auto overhead = header_span + alignment - 1;
}

extern "C" void *__wrap___cxa_allocate_exception(std::size_t size) noexcept
{
  if(size > std::numeric_limits<std::size_t>::max() - overhead)
  {
    std::terminate();
  }

  auto space = size + overhead;
  void *block = GC_malloc_uncollectable(space);
  if(!block)
  {
    std::terminate();
  }

  // Preserve libc++abi's alignment and header placement even on wasm32.
  auto const start = std::align(alignment, header_span + size, block, space);
  return static_cast<std::byte *>(start) + header_span;
}

extern "C" void __wrap___cxa_free_exception(void *exception) noexcept
{
  auto const start = static_cast<std::byte *>(exception) - header_span;
  GC_free(GC_base(start));
}
