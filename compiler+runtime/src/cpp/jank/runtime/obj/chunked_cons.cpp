#include <jank/runtime/obj/chunked_cons.hpp>
#include <jank/runtime/obj/persistent_list.hpp>
#include <jank/runtime/visit.hpp>
#include <jank/runtime/core/make_box.hpp>
#include <jank/runtime/core/seq.hpp>
#include <jank/runtime/behavior/chunkable.hpp>
#include <jank/util/fmt.hpp>

namespace jank::runtime::obj
{
  chunked_cons::chunked_cons()
    : object{ obj_type, obj_behaviors }
  {
  }

  chunked_cons::chunked_cons(object_ref const head, object_ref const tail)
    : object{ obj_type, obj_behaviors }
    , head{ head }
    , tail{ tail }
  {
    jank_debug_assert(head.is_some());
  }

  chunked_cons::chunked_cons(object_ref const meta, object_ref const head, object_ref const tail)
    : object{ obj_type, obj_behaviors }
    , head{ head }
    , tail{ tail }
    , meta{ meta }
  {
    jank_debug_assert(head.is_some());
    jank_debug_assert(meta.is_some());
  }

  object_ref chunked_cons::seq() const
  {
    return runtime::detail::untagged(this);
  }

  object_ref chunked_cons::fresh_seq() const
  {
    return make_box<chunked_cons>(head, tail);
  }

  object_ref chunked_cons::first() const
  {
    /* TODO: Port visit_object: chunk_like. */
    return visit_object(
      [&](auto const typed_head) -> object_ref {
        using T = typename decltype(typed_head)::value_type;

        if constexpr(behavior::chunk_like<T>)
        {
          return typed_head->nth(make_box(0));
        }
        else
        {
          throw std::runtime_error{ util::format(
            "The `chunked_cons` head is not chunk-like. It has type `{}`.",
            object_type_str(typed_head.get_type())) };
        }
      },
      head);
  }

  object_ref chunked_cons::next() const
  {
    /* TODO: Port visit_object: chunk_like. */
    return visit_object(
      [&](auto const typed_head) -> object_ref {
        using T = typename decltype(typed_head)::value_type;

        if constexpr(behavior::chunk_like<T>)
        {
          if(1 < typed_head->count())
          {
            return make_box<chunked_cons>(typed_head->chunk_next(), tail);
          }
          return runtime::seq(tail);
        }
        else
        {
          throw std::runtime_error{ util::format(
            "The `chunked_cons` head is not chunk-like. It has type `{}`.",
            object_type_str(typed_head.get_type())) };
        }
      },
      head);
  }

  object_ref chunked_cons::more() const
  {
    return visit_object(
      [&](auto const typed_head) -> object_ref {
        using T = typename decltype(typed_head)::value_type;
        if constexpr(behavior::chunk_like<T>)
        {
          if(1 < typed_head->count())
          {
            return make_box<chunked_cons>(typed_head->chunk_next(), tail);
          }
          return chunked_more();
        }
        else
        {
          throw std::runtime_error{ "The `chunked_cons` head is not chunk-like." };
        }
      },
      head);
  }

  object_ref chunked_cons::next_in_place()
  {
    /* TODO: Port visit_object: chunk_like. */
    return visit_object(
      [&](auto const typed_head) -> object_ref {
        using T = typename decltype(typed_head)::value_type;

        if constexpr(behavior::chunk_like<T>)
        {
          if(1 < typed_head->count())
          {
            head = typed_head->chunk_next();
            return runtime::detail::untagged(this);
          }
          return runtime::seq(tail);
        }
        else
        {
          throw std::runtime_error{ "The `chunked_cons` head is not chunk-like." };
        }
      },
      head);
  }

  object_ref chunked_cons::chunked_first() const
  {
    /* TODO: Port visit_object: chunk_like. */
    return visit_object(
      [&](auto const typed_head) -> object_ref {
        using T = typename decltype(typed_head)::value_type;

        if constexpr(behavior::chunk_like<T>)
        {
          return typed_head;
        }
        else
        {
          auto const buffer(make_box<chunk_buffer>(static_cast<size_t>(1)));
          buffer->append(typed_head);
          return buffer->chunk();
        }
      },
      head);
  }

  object_ref chunked_cons::chunked_next() const
  {
    return runtime::seq(tail);
  }

  object_ref chunked_cons::chunked_more() const
  {
    return tail.is_nil() ? object_ref{ persistent_list::empty() } : tail;
  }

  bool chunked_cons::equal(object const &o) const
  {
    return runtime::sequence_equal(runtime::detail::untagged(this), runtime::detail::untagged(&o));
  }

  void chunked_cons::to_string(jtl::string_builder &buff) const
  {
    runtime::seq_to_string(seq(), buff);
  }

  jtl::immutable_string chunked_cons::to_string() const
  {
    return runtime::seq_to_string(seq());
  }

  jtl::immutable_string chunked_cons::to_code_string() const
  {
    return runtime::seq_to_code_string(seq());
  }

  uhash chunked_cons::to_hash() const
  {
    return hash::ordered(runtime::detail::untagged(this));
  }

  cons_ref chunked_cons::conj(object_ref const head) const
  {
    return make_box<cons>(head, runtime::detail::untagged(this));
  }

  chunked_cons_ref chunked_cons::with_meta(object_ref const m) const
  {
    auto const meta(behavior::detail::validate_meta(m));
    auto const ret(expect_object<obj::chunked_cons>(fresh_seq()));
    ret->meta = meta;
    return ret;
  }

  object_ref chunked_cons::get_meta() const
  {
    return meta.get();
  }

  void chunked_cons::set_meta(object_ref const o)
  {
    auto const new_meta(behavior::detail::validate_meta(o));
    meta.set(new_meta);
  }
}
