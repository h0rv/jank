#include <jank/runtime/core/seq.hpp>
#include <jank/runtime/core/make_box.hpp>
#include <jank/runtime/obj/persistent_vector.hpp>
#include <jank/runtime/obj/persistent_list.hpp>
#include <jank/runtime/convert/builtin.hpp>

/* This must go last; doctest and glog both define CHECK and family. */
#include <doctest/doctest.h>

namespace jank::runtime::core
{
  TEST_SUITE("core runtime for seq")
  {
    TEST_CASE("numeric reference representation")
    {
      for(i64 const value : { i64{ -2147483648LL }, i64{ 0 }, i64{ 2147483647LL },
                             i64{ 2147483648LL } })
      {
        object_ref const boxed{ make_box(value) };
        object_ref const heap{ make_box<obj::integer>(value) };
        CHECK(boxed.equal(heap));
        CHECK(heap.equal(boxed));
        CHECK(boxed.to_hash() == heap.to_hash());
        CHECK(convert<i64>::from_object(boxed) == value);
      }
      object_ref const real{ make_box(1.25) };
      object_ref const heap_real{ make_box<obj::real>(1.25) };
      CHECK(real.equal(heap_real));
      CHECK(heap_real.equal(real));
      CHECK(real.to_hash() == heap_real.to_hash());
      CHECK(convert<f64>::from_object(real) == 1.25);
      CHECK(object_ref{}.is_nil());
      CHECK_THROWS_AS(convert<i64>::from_object(object_ref{}), std::runtime_error);
    }

    TEST_CASE("sequence_equal")
    {
      CHECK(sequence_equal(jank_nil, make_box<obj::persistent_vector>()));
      CHECK(sequence_equal(make_box<obj::persistent_vector>(), jank_nil));
      CHECK(sequence_equal(make_box<obj::persistent_vector>(), jank_nil));
      CHECK(sequence_equal(make_box<obj::persistent_vector>(std::in_place, make_box('f')),
                           make_box<obj::persistent_list>(std::in_place, make_box('f'))));
      CHECK(!sequence_equal(make_box<obj::persistent_vector>(std::in_place, make_box('f')),
                            make_box<obj::persistent_list>(std::in_place, make_box('g'))));
      CHECK(!sequence_equal(
        make_box<obj::persistent_vector>(std::in_place, make_box('f'), make_box('g')),
        make_box<obj::persistent_list>(std::in_place, make_box('g'), make_box('f'))));
      CHECK(sequence_equal(
        make_box<obj::persistent_vector>(std::in_place, make_box('f'), make_box('g')),
        make_box<obj::persistent_list>(std::in_place, make_box('f'), make_box('g'))));
      CHECK(!sequence_equal(
        make_box<obj::persistent_vector>(std::in_place, make_box('f')),
        make_box<obj::persistent_list>(std::in_place, make_box('g'), make_box('f'))));
      CHECK(!sequence_equal(
        make_box<obj::persistent_vector>(std::in_place, make_box('f'), make_box('g')),
        make_box<obj::persistent_list>(std::in_place, make_box('g'))));
    }
  }
}
