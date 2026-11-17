// AI-assisted isolated C++ exception probe, not a jank runtime test.
#include <cstdio>
__attribute__((noinline)) void fail() { throw 42; }
int main() {
  try { fail(); } catch (int value) {
    std::printf("C++ exception caught: %d\n", value);
    return value == 42 ? 0 : 1;
  }
  return 2;
}
