typedef __externref_t Ref;
__attribute__((import_module("gc"), import_name("alloc"))) Ref alloc(int);
__attribute__((import_module("gc"), import_name("read"))) int read_box(Ref);
static Ref roots[0];
void init(void) { __builtin_wasm_table_grow(roots, __builtin_wasm_ref_null_extern(), 1); }
struct LinearCell { unsigned handle; int bias; };
static struct LinearCell cell;
int hybrid(int value) {
  cell.handle = 0;
  cell.bias = 1;
  __builtin_wasm_table_set(roots, cell.handle, alloc(value));
  int result = read_box(__builtin_wasm_table_get(roots, cell.handle)) + cell.bias;
  __builtin_wasm_table_set(roots, cell.handle, __builtin_wasm_ref_null_extern());
  return result;
}
