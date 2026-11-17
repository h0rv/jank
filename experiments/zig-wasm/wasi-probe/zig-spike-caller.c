/* AI-assisted isolated caller for the unchanged native.zig ABI. */
typedef __SIZE_TYPE__ usize;
extern long long spike_add(int, int);
extern int spike_sum_i32(const int *, usize, long long *);
__attribute__((export_name("run"))) int run(void) {
  if (spike_add(20,22)!=42 || spike_add(2147483647,2147483647)!=4294967294LL) return 1;
  int values[4]={10,-3,20,15}; long long result=99;
  if (spike_sum_i32(values,4,&result)!=0 || result!=42) return 2;
  if (spike_sum_i32(values,4,&result)!=0 || result!=42 || values[1]!=-3) return 3;
  if (spike_sum_i32(0,0,&result)!=0 || result!=0) return 4;
  if (spike_sum_i32(values,0,&result)!=0 || result!=0) return 5;
  result=99;
  if (spike_sum_i32(0,1,&result)!=1 || result!=99) return 6;
  if (spike_sum_i32(0,0,0)!=1) return 7;
  return 0;
}
