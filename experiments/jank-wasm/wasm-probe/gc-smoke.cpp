#include <gc/gc.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

static_assert(sizeof(void *) == 8, "This experiment requires wasm64 pointers");

struct Node {
  Node *next;
  std::uint64_t value;
};

#ifdef GC_EXPLICIT_ROOTS
// This control test does not rely on Wasm local scanning.
static Node *registered_root;
#endif

[[gnu::noinline]] static Node *make_chain() {
  Node *head = nullptr;
  for (std::uint64_t i = 0; i < 128; ++i) {
    auto *node = static_cast<Node *>(GC_MALLOC(sizeof(Node)));
    if (!node) std::abort();
    node->next = head;
    node->value = i ^ UINT64_C(0x123456789abcdef0);
    head = node;
#ifdef GC_EXPLICIT_ROOTS
    registered_root = head;
#endif
  }
  return head;
}

// This function cannot see the caller's root. The documented Binaryen
// spill-pointers pass must make live Wasm locals visible to the collector.
[[gnu::noinline]] static void churn_and_collect() {
  for (int i = 0; i < 4096; ++i) {
    auto *bytes = static_cast<volatile unsigned char *>(GC_MALLOC_ATOMIC(256));
    if (!bytes) std::abort();
    bytes[0] = static_cast<unsigned char>(i);
  }
  GC_gcollect();
}

int main() {
  GC_INIT();
#ifdef GC_EXPLICIT_ROOTS
  GC_add_roots(&registered_root, &registered_root + 1);
#endif
  Node *root = make_chain();
  const auto before = GC_get_gc_no();
  for (int round = 0; round < 32; ++round) {
    churn_and_collect();
    Node *cursor = root;
    for (int i = 127; i >= 0; --i) {
      if (!cursor || cursor->value !=
                         (static_cast<std::uint64_t>(i) ^
                          UINT64_C(0x123456789abcdef0))) {
        std::fprintf(stderr, "FAIL: lost raw-pointer chain at round %d node %d\n",
                     round, i);
        std::abort();
      }
      cursor = cursor->next;
    }
    if (cursor) std::abort();
  }
  const auto collections = GC_get_gc_no() - before;
  if (collections < 32) std::abort();
#ifdef GC_EXPLICIT_ROOTS
  std::printf("Root strategy: explicit GC_add_roots slot (control test)\n");
#else
  std::printf("Root strategy: raw local pointer\n");
#endif
  std::printf("PASS: wasm64, 128 nodes, 32 forced collections; "
              "collections=%llu allocated=%zu heap=%zu pointer_bits=%zu\n",
              static_cast<unsigned long long>(collections),
              GC_get_total_bytes(), GC_get_heap_size(), sizeof(void *) * 8);
  GC_reachable_here(root);
}
