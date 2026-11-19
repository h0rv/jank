(module
  (type $box (struct (field i32)))
  (type $cons (struct (field (ref $box)) (field (ref null $cons))))
  (func (export "churn") (param $n i32) (result i32)
    (local $i i32) (local $cell (ref null $cons))
    (loop $loop
      (local.set $cell (struct.new $cons
        (struct.new $box (local.get $i)) (ref.null $cons)))
      (local.set $i (i32.add (local.get $i) (i32.const 1)))
      (br_if $loop (i32.lt_u (local.get $i) (local.get $n))))
    (struct.get $box 0 (struct.get $cons 0 (ref.as_non_null (local.get $cell)))))
  (func (export "alloc") (param $x i32) (result externref)
    (extern.convert_any (struct.new $box (local.get $x))))
  (func (export "read") (param $x externref) (result i32)
    (struct.get $box 0 (ref.cast (ref $box) (any.convert_extern (local.get $x)))))
)
