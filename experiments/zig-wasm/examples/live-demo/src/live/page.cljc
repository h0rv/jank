;; AI-assisted page bridge: Module.liveInput in, Module.onLiveLine and onLiveFinish out.
(ns live.page)

#?(:wasm
   (cpp/raw "#include <string>
#ifdef __EMSCRIPTEN__
#include <emscripten.h>
EM_JS(int, live_input_size, (), {
  const text = Module.liveInput;
  return typeof text === 'string' ? lengthBytesUTF8(text) : -1;
});
EM_JS(void, live_input_copy, (char *out, int size), {
  stringToUTF8(Module.liveInput, Number(out), size + 1);
  Module.liveInput = null;
});
EM_JS(void, live_show, (char const *text), {
  Module.onLiveLine?.(UTF8ToString(Number(text)));
});
EM_JS(void, live_finish, (char const *text), {
  Module.onLiveFinish?.(UTF8ToString(Number(text)));
});
#else
inline int live_input_size() { return -1; }
inline void live_input_copy(char *, int) {}
inline void live_show(char const *) {}
inline void live_finish(char const *) {}
#endif
inline jank::runtime::object_ref live_take_input()
{
  int const size{ live_input_size() };
  if(size < 0) { return jank::runtime::jank_nil; }
  std::string text(size + 1, '\\0');
  live_input_copy(text.data(), size);
  text.resize(size);
  return jank::runtime::make_box<jank::runtime::obj::persistent_string>(
    jtl::immutable_string{ text.data(), text.size() });
}"))

#?(:wasm
   (defn take-input [] (cpp/live_take_input))
   :native
   (defn take-input [] nil))

#?(:wasm
   (defn show [text] (cpp/live_show (cpp/.c_str (cpp/jank.runtime.to_string text))))
   :native
   (defn show [text] (println text)))

#?(:wasm
   (defn finish [text] (cpp/live_finish (cpp/.c_str (cpp/jank.runtime.to_string text))))
   :native
   (defn finish [text] (println text)))
