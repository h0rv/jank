/* AI-assisted scratch storage reserved in the main module's linear memory. */
static unsigned char scratch[262144] __attribute__((aligned(16)));
__attribute__((export_name("wasi_shim_scratch"))) unsigned long long wasi_shim_scratch(void) {
  return (unsigned long long)scratch;
}
