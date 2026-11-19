// Isolated form of jank's tagged-pointer encoding, not the full oref class.
// This checks representation only. It does NOT test GC root discovery.
using u64 = unsigned long long;
static_assert(sizeof(void*) == sizeof(u64));

struct Cell { long long value; };
alignas(8) static Cell live{42};

extern "C" int nanbox_round_trip()
{
  constexpr u64 tag = 0xFFFa000000000000ull;
  constexpr u64 mask = 0x0000FFFFFFFFFFFFull;
  const auto address = reinterpret_cast<u64>(&live);
  if((address & ~mask) != 0) return 1;
  void* encoded = __builtin_bit_cast(void*, tag | address);
  const auto bits = __builtin_bit_cast(u64, encoded);
  if((bits & ~mask) != tag) return 2;
  auto* decoded = __builtin_bit_cast(Cell*, bits & mask);
  return decoded->value == 42 ? 0 : 3;
}
