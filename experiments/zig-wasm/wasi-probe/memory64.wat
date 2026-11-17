;; AI-assisted core memory64 control without WASI imports.
(module
  (memory (export "memory") i64 1)
  (func (export "check") (result i64)
    (i64.store (i64.const 8) (i64.const 42))
    (i64.load (i64.const 8))))
