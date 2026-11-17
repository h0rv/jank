/* AI-assisted spill probe with a value live across an imported callback. */
extern unsigned long long collect(unsigned long long);
__attribute__((export_name("check"))) unsigned long long check(unsigned long long value) {
  unsigned long long result = collect(value);
  return value + result;
}
