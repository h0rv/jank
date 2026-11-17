#include <jank/runtime/obj/integer_range.hpp>
#include <jank/runtime/obj/array_chunk.hpp>
#include <jank/runtime/core/math.hpp>
#include <jank/runtime/core/make_box.hpp>
#include <jank/runtime/core/seq.hpp>
#include <jank/runtime/visit.hpp>
#include <jank/runtime/behavior/metadatable.hpp>

namespace jank::runtime::obj
{
  static bool positive_step_bounds_check(i64 const val, i64 const end)
  {
    return end <= val;
  }

  static bool negative_step_bounds_check(i64 const val, i64 const end)
  {
    return val <= end;
  }

  integer_range::integer_range()
    : object{ obj_type, obj_behaviors }
  {
  }

  integer_range::integer_range(i64 const end)
    : object{ obj_type, obj_behaviors }
    , end{ end }
    , bounds_check{ static_cast<bounds_check_t>(positive_step_bounds_check) }
  {
  }

  integer_range::integer_range(i64 const start, i64 const end)
    : object{ obj_type, obj_behaviors }
    , start{ start }
    , end{ end }
    , bounds_check{ static_cast<bounds_check_t>(positive_step_bounds_check) }
  {
  }

  integer_range::integer_range(i64 const start, i64 const end, i64 const step)
    : object{ obj_type, obj_behaviors }
    , start{ start }
    , end{ end }
    , step{ step }
    , bounds_check{ 0 < step ? static_cast<bounds_check_t>(positive_step_bounds_check)
                             : static_cast<bounds_check_t>(negative_step_bounds_check) }
  {
  }

  integer_range::integer_range(i64 const start,
                               i64 const end,
                               i64 const step,
                               integer_range::bounds_check_t const bounds_check)
    : object{ obj_type, obj_behaviors }
    , start{ start }
    , end{ end }
    , step{ step }
    , bounds_check{ bounds_check }
  {
  }

  object_ref integer_range::create(i64 const end)
  {
    if(0 < end)
    {
      return make_box<integer_range>(0,
                                     end,
                                     1,
                                     static_cast<bounds_check_t>(positive_step_bounds_check));
    }
    return persistent_list::empty();
  }

  object_ref integer_range::create(i64 const start, i64 const end)
  {
    return create(start, end, 1);
  }

  object_ref integer_range::create(i64 const start, i64 const end, i64 const step)
  {
    if(((0 < step) && (end < start)) || ((step < 0) && (start < end)) || (start == end))
    {
      return persistent_list::empty();
    }

    else if(step == 0)
    {
      return repeat::create(make_box(start));
    }
    return make_box<integer_range>(start,
                                   end,
                                   step,
                                   0 < step
                                     ? static_cast<bounds_check_t>(positive_step_bounds_check)
                                     : static_cast<bounds_check_t>(negative_step_bounds_check));
  }

  object_ref integer_range::seq() const
  {
    return runtime::detail::untagged(this);
  }

  object_ref integer_range::fresh_seq() const
  {
    return make_box<integer_range>(start, end, step, bounds_check);
  }

  object_ref integer_range::first() const
  {
    return make_box(start);
  }

  object_ref integer_range::next() const
  {
    i64 val{};
    if(__builtin_add_overflow(start, step, &val) || bounds_check(val, end))
    {
      return {};
    }
    return make_box<integer_range>(val, end, step, bounds_check);
  }

  object_ref integer_range::next_in_place()
  {
    i64 val{};
    if(__builtin_add_overflow(start, step, &val) || bounds_check(val, end))
    {
      return {};
    }
    start = val;
    return runtime::detail::untagged(this);
  }

  array_chunk_ref integer_range::chunked_first() const
  {
    native_vector<object_ref> buffer;
    buffer.reserve(chunk_size);
    i64 val{ start };
    for(usize i{}; i < chunk_size; ++i)
    {
      buffer.emplace_back(make_box(val));
      if(__builtin_add_overflow(val, step, &val) || bounds_check(val, end))
      {
        break;
      }
    }
    return make_box<array_chunk>(std::move(buffer), usize{});
  }

  integer_range_ref integer_range::chunked_next() const
  {
    i64 val{ start };
    for(usize i{}; i < chunk_size; ++i)
    {
      if(__builtin_add_overflow(val, step, &val) || bounds_check(val, end))
      {
        return {};
      }
    }
    return make_box<integer_range>(val, end, step, bounds_check);
  }

  object_ref integer_range::chunked_more() const
  {
    auto const more{ chunked_next() };
    return more.is_nil() ? object_ref{ persistent_list::empty() } : more.erase();
  }

  cons_ref integer_range::conj(object_ref const head) const
  {
    return make_box<cons>(head, runtime::detail::untagged(this));
  }

  persistent_list_ref integer_range::empty()
  {
    return persistent_list::empty();
  }

  bool integer_range::equal(object const &o) const
  {
    return runtime::sequence_equal(runtime::detail::untagged(this), runtime::detail::untagged(&o));
  }

  void integer_range::to_string(jtl::string_builder &buff) const
  {
    runtime::seq_to_string(seq(), buff);
  }

  jtl::immutable_string integer_range::to_string() const
  {
    return runtime::seq_to_string(seq());
  }

  jtl::immutable_string integer_range::to_code_string() const
  {
    return runtime::seq_to_code_string(seq());
  }

  uhash integer_range::to_hash() const
  {
    return hash::ordered(runtime::detail::untagged(this));
  }

  integer_range_ref integer_range::with_meta(object_ref const m) const
  {
    auto const meta(behavior::detail::validate_meta(m));
    auto const ret(expect_object<obj::integer_range>(fresh_seq()));
    ret->meta = meta;
    return ret;
  }

  object_ref integer_range::get_meta() const
  {
    return meta.get();
  }

  void integer_range::set_meta(object_ref const o)
  {
    auto const new_meta(behavior::detail::validate_meta(o));
    meta.set(new_meta);
  }

  usize integer_range::count() const
  {
    auto const s{ step };
    if(s == 0)
    {
      throw std::runtime_error("integer_range step shouldn't be 0.");
    }

    auto const diff{ s > 0 ? static_cast<u64>(end) - static_cast<u64>(start)
                           : static_cast<u64>(start) - static_cast<u64>(end) };
    auto const stride{ s > 0 ? static_cast<u64>(s) : u64{} - static_cast<u64>(s) };
    return static_cast<usize>(diff / stride + (diff % stride != 0));
  }
}
