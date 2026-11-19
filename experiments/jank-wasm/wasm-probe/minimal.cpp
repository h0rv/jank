// A minimal C++ caller linked with our real Zig implementation.
// No jank runtime, libc, allocator or garbage collector is included here.
extern "C" long long spike_add(int, int);

class Adder
{
public:
  explicit Adder(int first) : first_{first} {}
  long long add(int second) const { return spike_add(first_, second); }
private:
  int first_;
};

extern "C" long long cpp_calls_zig(int first, int second)
{
  return Adder{first}.add(second);
}
