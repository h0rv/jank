#include <vector>

// Exercise C++ dynamic allocation and RAII independently of jank and its GC.
extern "C" long long cpp_vector_sum(int count)
{
  if(count < 0 || count > 1024) return -1;
  std::vector<int> values;
  for(int i = 0; i < count; ++i) values.push_back(i);
  long long total = 0;
  for(int value : values) total += value;
  return total;
}
