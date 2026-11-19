;; AI-assisted memory64 control using the host's i32 Preview 1 pointer ABI.
(module
  (import "wasi_snapshot_preview1" "fd_write"
    (func $write (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") i64 1)
  (data (i64.const 0) "\10\00\00\00\14\00\00\00")
  (data (i64.const 16) "memory64 ABI32 WASI!\0a")
  (func (export "_start")
    (if (call $write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 8))
      (then unreachable))))
