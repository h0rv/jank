#include <jank/runtime/core/seq.hpp>
#include <jank/runtime/core.hpp>
#include <jank/runtime/core/make_box.hpp>
#include <jank/runtime/obj/native_vector_sequence.hpp>
#include <jank/runtime/obj/persistent_array_map.hpp>
#include <jank/runtime/obj/persistent_vector.hpp>
#include <jank/runtime/obj/persistent_list.hpp>
#include <jank/runtime/convert/builtin.hpp>

/* This must go last; doctest and glog both define CHECK and family. */
#include <doctest/doctest.h>

namespace jank::runtime::core
{
  TEST_SUITE("core runtime for seq")
  {
    TEST_CASE("native vector sequence shared backing")
    {
      native_vector<object_ref> values{ make_box(1), make_box(2), make_box(3) };
      auto const s{ make_box<obj::native_vector_sequence>(values, 0) };
      values[0] = make_box(99);
      CHECK(s->first().equal(make_box(1)));
      CHECK(s->seq() == s.erase());
      auto const tail{ expect_object<obj::native_vector_sequence>(s->next()) };
      auto const fresh{ expect_object<obj::native_vector_sequence>(tail->fresh_seq()) };
      auto const decorated{ tail->with_meta(make_box<obj::persistent_array_map>()) };
      auto const copied{ make_box<obj::native_vector_sequence>(*tail) };
      CHECK(s->data == tail->data);
      CHECK(tail->data == fresh->data);
      CHECK(tail->data == decorated->data);
      CHECK(tail->data == copied->data);
      CHECK(fresh != tail);
      CHECK(decorated != tail);
      CHECK(fresh->index == 1);
      CHECK(decorated->index == 1);
      CHECK(rest(s) != s.erase());
      CHECK(rest(s).equal(tail));
      CHECK(tail->to_string() == "(2 3)");
      CHECK(tail->to_code_string() == "(2 3)");
      CHECK(tail->to_hash() == fresh->to_hash());
      CHECK(fresh->next_in_place() == fresh.erase());
      CHECK(fresh->first().equal(make_box(3)));
      CHECK(tail->first().equal(make_box(2)));
      CHECK(s->count() == 3);
      CHECK(fresh->next_in_place().is_nil());
      CHECK(fresh->next_in_place().is_nil());
      CHECK(fresh->count() == 0);
      CHECK(fresh->seq().is_nil());
      CHECK(fresh->first().is_nil());
      CHECK(tail->count() == 2);
    }

    TEST_CASE("native vector sequence moved backing and empty cursors")
    {
      native_vector<object_ref> values{ make_box(1), make_box(2) };
      auto const storage{ values.data() };
      auto const s{ make_box<obj::native_vector_sequence>(std::move(values), 1) };
      CHECK(s->data->data() == storage);
      CHECK(s->count() == 1);
      CHECK(s->first().equal(make_box(2)));
      CHECK(s->next().is_nil());
      CHECK(s->count() == 1);
      for(auto const empty : { make_box<obj::native_vector_sequence>(),
                               make_box<obj::native_vector_sequence>(native_vector<object_ref>{}) })
      {
        CHECK(empty->count() == 0);
        CHECK(empty->seq().is_nil());
        CHECK(empty->fresh_seq().is_nil());
        CHECK(empty->next().is_nil());
        CHECK(empty->next_in_place().is_nil());
        CHECK(empty->first().is_nil());
        CHECK(empty->with_meta(make_box<obj::persistent_array_map>())->count() == 0);
      }
    }

    TEST_CASE("native vector sequence namespace producer")
    {
      auto const namespaces{ runtime::all_ns() };
      REQUIRE(namespaces->count() > 1);
      auto const fresh{ expect_object<obj::native_vector_sequence>(namespaces->fresh_seq()) };
      CHECK(namespaces->data == fresh->data);
      auto const size{ namespaces->count() };
      fresh->next_in_place();
      CHECK(namespaces->count() == size);
      CHECK(fresh->count() == size - 1);
    }

    TEST_CASE("native vector sequence backing is GC traced")
    {
      auto const tail{ [] {
        native_vector<object_ref> values{ make_box(0), make_box("shared backing payload") };
        return make_box<obj::native_vector_sequence>(std::move(values))->next();
      }() };
      GC_gcollect();
      CHECK(tail.first().to_string() == "shared backing payload");
      CHECK(expect_object<obj::native_vector_sequence>(tail)->count() == 1);
    }

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
