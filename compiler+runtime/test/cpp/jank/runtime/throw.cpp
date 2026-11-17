#include <exception>
#include <memory>
#include <stdexcept>
#include <type_traits>
#include <utility>

#include <gc/gc_mark.h>

#include <jank/c_api.h>
#include <jank/error.hpp>
#include <jank/runtime/core/make_box.hpp>
#include <jank/runtime/context.hpp>
#include <jank/runtime/throw.hpp>

/* This must go last; doctest and glog both define CHECK and family. */
#include <doctest/doctest.h>

namespace jank::runtime
{
  namespace
  {
    constexpr i64 payload_value{ 0x123456789abcdef };

    struct observer
    {
      observer()
        : link{ static_cast<void **>(GC_MALLOC_ATOMIC_UNCOLLECTABLE(sizeof(void *))) }
      {
        if(!link)
        {
          std::terminate();
        }
      }

      observer(observer const &) = delete;
      observer &operator=(observer const &) = delete;

      ~observer()
      {
        GC_unregister_disappearing_link(link);
        GC_FREE(link);
      }

      [[gnu::noinline]]
      void watch(void * const value)
      {
        *link = reinterpret_cast<void *>(GC_HIDE_POINTER(value));
        REQUIRE_EQ(GC_general_register_disappearing_link(link, value), GC_SUCCESS);
      }

      bool alive() const
      {
        return *link != nullptr;
      }

      void **link;
    };

    [[gnu::noinline]]
    void collect()
    {
      for(int i{}; i < 4096; ++i)
      {
        make_box(payload_value + i);
      }
      GC_clear_stack(nullptr);
      GC_gcollect();
    }

    struct collect_on_unwind
    {
      observer const &watched;
      bool &retained;
      size_t &collections;

      ~collect_on_unwind()
      {
        collect();
        retained &= watched.alive();
        ++collections;
      }
    };

    [[gnu::noinline]]
    object_ref payload(observer &watched)
    {
      auto const value{ make_box(payload_value) };
      watched.watch(detail::as_pointer(value.erase().raw()));
      return value;
    }

    [[gnu::noinline]]
    void raise(observer &watched, bool &retained, size_t &collections)
    {
      collect_on_unwind guard{ watched, retained, collections };
      jank_throw(payload(watched).raw());
    }

    [[gnu::noinline]]
    void exercise(observer &watched, int const mode)
    {
      bool caught_payload{};
      bool retained{ true };
      size_t collections{};
      std::exception_ptr saved;
      try
      {
        try
        {
          raise(watched, retained, collections);
        }
        catch(object_ref const &value)
        {
          caught_payload = true;
          collect();
          REQUIRE(watched.alive());
          CHECK_EQ(value.to_integer(), payload_value);
          CHECK(retained);
          CHECK_EQ(collections, 1);
          if(mode == 1)
          {
            throw;
          }
          if(mode == 2)
          {
            saved = std::current_exception();
          }
          if(mode == 3)
          {
            observer inner;
            bool inner_retained{ true };
            size_t inner_collections{};
            try
            {
              raise(inner, inner_retained, inner_collections);
            }
            catch(object_ref const nested)
            {
              collect();
              REQUIRE(inner.alive());
              REQUIRE(watched.alive());
              CHECK_EQ(nested.to_integer(), payload_value);
              CHECK(inner_retained);
              CHECK_EQ(inner_collections, 1);
            }
          }
          if(mode == 4)
          {
            std::throw_with_nested(std::runtime_error{ "nested" });
          }
        }
      }
      catch(object_ref const value)
      {
        collect();
        REQUIRE(watched.alive());
        CHECK_EQ(value.to_integer(), payload_value);
        CHECK_EQ(mode, 1);
      }
      catch(std::exception const &outer)
      {
        CHECK_EQ(mode, 4);
        collect();
        REQUIRE(watched.alive());
        bool caught{};
        try
        {
          std::rethrow_if_nested(outer);
        }
        catch(object_ref const &value)
        {
          caught = true;
          collect();
          REQUIRE(watched.alive());
          CHECK_EQ(value.to_integer(), payload_value);
        }
        CHECK(caught);
      }
      CHECK(caught_payload);
      if(mode == 2)
      {
        REQUIRE(static_cast<bool>(saved));
        auto copy{ saved };
        saved = {};
        collect();
        REQUIRE(watched.alive());
        try
        {
          std::rethrow_exception(copy);
        }
        catch(object_ref const &value)
        {
          collect();
          REQUIRE(watched.alive());
          CHECK_EQ(value.to_integer(), payload_value);
        }
      }
    }

    [[gnu::noinline]]
    error_ref error_payload(observer &watched)
    {
      auto const value{ make_error(error::kind::runtime_uncaught_exception,
                                   read::source::unknown()) };
      watched.watch(value.get());
      return value;
    }

    [[gnu::noinline]]
    void raise_error(observer &watched, bool &retained, size_t &collections)
    {
      collect_on_unwind guard{ watched, retained, collections };
      throw_error(error_payload(watched));
    }

    [[gnu::noinline]]
    void exercise_error(observer &watched)
    {
      bool retained{ true };
      size_t collections{};
      std::exception_ptr saved;
      try
      {
        try
        {
          raise_error(watched, retained, collections);
        }
        catch(error_ref const &)
        {
          collect();
          REQUIRE(watched.alive());
          throw;
        }
      }
      catch(error_ref const &value)
      {
        saved = std::current_exception();
        collect();
        REQUIRE(watched.alive());
        CHECK(retained);
        CHECK_EQ(collections, 1);
        CHECK_EQ(value->kind, error::kind::runtime_uncaught_exception);
      }
      REQUIRE(static_cast<bool>(saved));
      auto copy{ saved };
      saved = {};
      collect();
      REQUIRE(watched.alive());
      try
      {
        std::rethrow_exception(copy);
      }
      catch(error_ref const value)
      {
        collect();
        REQUIRE(watched.alive());
        CHECK_EQ(value->kind, error::kind::runtime_uncaught_exception);
      }
    }

    [[gnu::noinline]]
    std::unique_ptr<thrown_object> make_owner(observer &watched)
    {
      return std::make_unique<thrown_object>(payload(watched));
    }

    [[gnu::noinline]]
    void exercise_owners(observer &first, observer &second)
    {
      auto original{ make_owner(first) };
      auto copied{ std::make_unique<thrown_object>(*original) };
      auto moved{ std::make_unique<thrown_object>(std::move(*original)) };
      original.reset();
      collect();
      REQUIRE(first.alive());
      CHECK_EQ(copied->to_integer(), payload_value);
      CHECK_EQ(moved->to_integer(), payload_value);
      *copied = payload(second);
      *moved = *copied;
      copied.reset();
      for(int i{}; i < 32 && first.alive(); ++i)
      {
        collect();
      }
      CHECK_FALSE(first.alive());
      REQUIRE(second.alive());
      auto assigned{ std::make_unique<thrown_object>(object_ref{}) };
      *assigned = std::move(*moved);
      moved.reset();
      collect();
      REQUIRE(second.alive());
      CHECK_EQ(assigned->to_integer(), payload_value);
    }
  }

  TEST_CASE("runtime exceptions own scanned roots until their last owner dies")
  {
    static_assert(!std::is_final_v<object_ref>);
    static_assert(std::is_base_of_v<object_ref, thrown_object>);
    static_assert(std::is_nothrow_copy_constructible_v<thrown_object>);
    static_assert(std::is_nothrow_move_constructible_v<thrown_object>);
    static_assert(std::is_nothrow_copy_assignable_v<thrown_object>);
    static_assert(std::is_nothrow_move_assignable_v<thrown_object>);
    static_assert(std::is_nothrow_destructible_v<thrown_object>);
    static_assert(std::is_nothrow_copy_constructible_v<thrown_error>);
    static_assert(std::is_nothrow_move_constructible_v<thrown_error>);
    for(int mode{}; mode < 5; ++mode)
    {
      CAPTURE(mode);
      observer watched;
      auto const before{ GC_get_gc_no() };
      exercise(watched, mode);
      for(int i{}; i < 32 && watched.alive(); ++i)
      {
        collect();
      }
      CHECK_FALSE(watched.alive());
      CHECK_GT(GC_get_gc_no(), before);
    }
    observer watched;
    exercise_error(watched);
    for(int i{}; i < 32 && watched.alive(); ++i)
    {
      collect();
    }
    CHECK_FALSE(watched.alive());
  }

  TEST_CASE("rooted exception copies moves and assignments preserve base values")
  {
    observer first, second;
    exercise_owners(first, second);
    for(int i{}; i < 32 && second.alive(); ++i)
    {
      collect();
    }
    CHECK_FALSE(second.alive());
    thrown_object original{ make_box(payload_value) };
    thrown_object copied{ original };
    thrown_object moved{ std::move(original) };
    copied = moved;
    moved = std::move(copied);
    collect();
    CHECK_EQ(original.to_integer(), payload_value);
    CHECK_EQ(copied.to_integer(), payload_value);
    CHECK_EQ(moved.to_integer(), payload_value);
    original = object_ref{};
    CHECK(original.is_nil());
    CHECK_EQ(moved.to_integer(), payload_value);
    CHECK_THROWS_AS(throw_object(object_ref{}), object_ref);
    CHECK_THROWS_AS(
      throw_error(make_error(error::kind::runtime_uncaught_exception, read::source::unknown())),
      error_ref);
  }

  TEST_CASE("generated throws use rooted runtime exceptions")
  {
    CHECK_THROWS_AS(__rt_ctx->eval_string("(throw :rooted)"), thrown_object);
    CHECK_THROWS_AS(
      __rt_ctx->eval_string("(throw (cpp/jank.error.internal_failure \"native error\"))"),
      thrown_error);
    CHECK_THROWS_AS(__rt_ctx->eval_string("(throw (cpp/int. 42))"), int);
  }
}
