#pragma once

#include <exception>
#include <type_traits>

#include <jank/runtime/object.hpp>

namespace jank::error
{
  struct base;
}

namespace jank::runtime::detail
{
  [[gnu::noinline]]
  void **allocate_exception_root(void *value) noexcept;

  template <typename Ref>
  class rooted_exception : public Ref
  {
    static_assert(sizeof(Ref) == sizeof(void *));

  public:
    explicit rooted_exception(Ref const value) noexcept
      : Ref{ value }
      , root{ allocate_exception_root(root_value(value)) }
    {
    }

    rooted_exception(rooted_exception const &other) noexcept
      : rooted_exception{ static_cast<Ref const &>(other) }
    {
    }

    rooted_exception(rooted_exception &&other) noexcept
      : rooted_exception{ static_cast<Ref const &>(other) }
    {
    }

    rooted_exception &operator=(rooted_exception const &other) noexcept
    {
      return operator=(static_cast<Ref const &>(other));
    }

    rooted_exception &operator=(Ref const value) noexcept
    {
      GC_PTR_STORE_AND_DIRTY(root, root_value(value));
      Ref::operator=(value);
      return *this;
    }

    rooted_exception &operator=(rooted_exception &&other) noexcept
    {
      return operator=(static_cast<rooted_exception const &>(other));
    }

    ~rooted_exception() noexcept
    {
      GC_FREE(root);
    }

  private:
    static void *root_value(Ref const value) noexcept
    {
      if constexpr(std::is_same_v<Ref, runtime::object_ref>)
      {
        return value.raw();
      }
      else
      {
        return value.get();
      }
    }

    void **root;
  };
}

namespace jank::runtime
{
  using thrown_object = detail::rooted_exception<object_ref>;

  [[noreturn]]
  void throw_object(object_ref value);
}

namespace jank
{
  using thrown_error = runtime::detail::rooted_exception<jtl::ref<error::base>>;

  [[noreturn]]
  void throw_error(jtl::ref<error::base> value);
}
