static __externref_t table[0];
extern "C" void init() { __builtin_wasm_table_grow(table, __builtin_wasm_ref_null_extern(), 1); }
extern "C" __externref_t pass(__externref_t x) { return x; }
extern "C" void put(__externref_t x) { __builtin_wasm_table_set(table, 0, x); }
extern "C" __externref_t get() { return __builtin_wasm_table_get(table, 0); }
extern "C" void clear() { __builtin_wasm_table_set(table, 0, __builtin_wasm_ref_null_extern()); }
#ifdef BAD_FIELD
struct Bad { __externref_t value; };
#endif
#ifdef BAD_HEAP
void heap() { new __externref_t; }
#endif
#ifdef BAD_ARRAY
__externref_t values[2];
#endif
#ifdef BAD_ADDRESS
void address(__externref_t x) { auto p = &x; }
#endif
#ifdef FUNCREF
using F = void (* __funcref)();
extern "C" F function_pass(F f) { return f; }
#endif
