#include <jank/runtime/obj/integer_range.hpp>
#include <jank/runtime/obj/array_chunk.hpp>
#include <jank/runtime/obj/chunked_cons.hpp>
#include <jank/runtime/obj/persistent_list.hpp>
#include <jank/runtime/core/make_box.hpp>
#include <jank/runtime/core/equal.hpp>
#include <jank/runtime/core/seq.hpp>
#include <jank/runtime/behavior/chunkable.hpp>
#include <jank/runtime/visit.hpp>

/* This must go last; doctest and glog both define CHECK and family. */
#include <doctest/doctest.h>

namespace jank::runtime::obj
{
  TEST_SUITE("integer_range")
  {
    TEST_CASE("chunked cons traversal")
    {
      auto const head{ make_box<array_chunk>(native_vector<object_ref>{ make_box(1), make_box(2) }) };
      auto const tail{ integer_range::create(3, 6) };
      auto const s{ make_box<chunked_cons>(head, tail) };
      CHECK(equal(s->more(), integer_range::create(2, 6)));
      CHECK(is_identical(s->chunked_more(), tail));
      CHECK(equal(s->chunked_next(), tail));
      CHECK(s->next_in_place().first().equal(make_box(2)));
      CHECK(equal(s->next_in_place(), tail));
      CHECK(s->first().equal(make_box(2)));
      auto const single{ make_box<array_chunk>(native_vector<object_ref>{ make_box(1) }) };
      auto const empty{ make_box<chunked_cons>(single, object_ref{}) };
      CHECK(empty->next().is_nil());
      CHECK(empty->next_in_place().is_nil());
      CHECK(empty->chunked_next().is_nil());
      CHECK(equal(empty->more(), persistent_list::empty()));
      CHECK(equal(empty->chunked_more(), persistent_list::empty()));
      auto const with_empty_tail{ make_box<chunked_cons>(single, persistent_list::empty()) };
      CHECK(with_empty_tail->next_in_place().is_nil());
      CHECK(with_empty_tail->chunked_next().is_nil());
    }

    TEST_CASE("chunks and sequence cursors")
    {
      static_assert(behavior::chunkable<integer_range>);
      for(i64 const step : { i64{ 1 }, i64{ -1 }, i64{ 3 }, i64{ -3 } })
      {
        for(i64 const size : { i64{ 1 }, i64{ 31 }, i64{ 32 }, i64{ 33 }, i64{ 65 } })
        {
          auto const range{ expect_object<integer_range>(integer_range::create(7, 7 + size * step, step)) };
          auto cursor{ range.erase() };
          i64 consumed{};
          while(!cursor.is_nil())
          {
            auto const r{ expect_object<integer_range>(cursor) };
            auto const c{ r->chunked_first() };
            auto const n{ std::min(i64{ 32 }, size - consumed) };
            CHECK(c->count() == static_cast<usize>(n));
            for(i64 i{}; i < n; ++i)
            {
              CHECK(c->nth(make_box(i)).equal(make_box(7 + (consumed + i) * step)));
            }
            consumed += n;
            cursor = r->chunked_next();
            CHECK(equal(r->chunked_more(), runtime::chunk_rest(r)));
          }
          CHECK(consumed == size);
          CHECK(range->start == 7);
          CHECK(range->count() == static_cast<usize>(size));
          if(size > 1)
          {
            auto const next{ expect_object<integer_range>(range->next()) };
            auto const fresh{ expect_object<integer_range>(range->fresh_seq()) };
            CHECK(next->first().equal(make_box(7 + step)));
            CHECK(fresh->next_in_place().equal(next));
            CHECK(range->start == 7);
            CHECK(next->chunked_first()->nth(make_box(0)).equal(next->first()));
          }
        }
      }
    }

    TEST_CASE("overflow boundaries")
    {
      auto const lo{ std::numeric_limits<i64>::min() };
      auto const hi{ std::numeric_limits<i64>::max() };
      for(auto const r : { expect_object<integer_range>(integer_range::create(lo, hi, hi)),
                           expect_object<integer_range>(integer_range::create(hi, lo, lo)),
                           expect_object<integer_range>(integer_range::create(hi - 2, hi, 3)),
                           expect_object<integer_range>(integer_range::create(lo + 2, lo, -3)) })
      {
        auto cursor{ r.erase() };
        usize n{};
        auto const c{ r->chunked_first() };
        while(!cursor.is_nil())
        {
          REQUIRE(n < 4);
          CHECK(cursor.first().equal(c->nth(make_box(n))));
          cursor = cursor.next();
          ++n;
        }
        CHECK(n == r->count());
        CHECK(n == c->count());
        CHECK(r->chunked_next().is_nil());
        CHECK(r->chunked_more().seq().is_nil());
      }
      auto const full{ expect_object<integer_range>(integer_range::create(lo, hi)) };
      CHECK(full->count() == std::numeric_limits<u64>::max());
      CHECK(full->chunked_first()->count() == 32);
      CHECK(full->chunked_next()->start == lo + 32);
      auto const descending{ expect_object<integer_range>(integer_range::create(hi, lo, -1)) };
      CHECK(descending->count() == std::numeric_limits<u64>::max());
      CHECK(descending->chunked_next()->start == hi - 32);
    }

    TEST_CASE("equal")
    {
      CHECK(equal(integer_range::create(5), integer_range::create(5)));
      CHECK(equal(integer_range::create(1), integer_range::create(1)));
      CHECK(!equal(integer_range::create(6), integer_range::create(5)));
      CHECK(!equal(integer_range::create(5), integer_range::create(6)));
      CHECK(equal(integer_range::create(0), integer_range::create(0)));
      CHECK(!equal(integer_range::create(0), integer_range::create(5)));
      CHECK(!equal(integer_range::create(1), integer_range::create(0)));
    }
  }
}
