;; AI-assisted reduction of the standardized EH instruction in wasi-sdk libraries.
(module
 (tag $exception)
 (func (export "f")
  (block $handler
   (try_table (catch_all $handler)
    (throw $exception)))))
