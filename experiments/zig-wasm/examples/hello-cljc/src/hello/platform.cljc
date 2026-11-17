;; AI-assisted thin platform layer; all computation lives in shared jank.
(ns hello.platform)

#?(:wasm
   (cpp/raw "#ifdef __EMSCRIPTEN__
#include <emscripten.h>
EM_JS(void, hello_emit, (const char* text), {
  const line = UTF8ToString(Number(text));
  if (typeof document !== 'undefined') {
    document.getElementById('app').textContent += line + '\\n';
  } else {
    console.log(line);
  }
});
EM_JS(int, hello_browser, (), { return typeof document !== 'undefined' ? 1 : 0; });
#else
#include <cstdio>
inline void hello_emit(const char* text) { std::puts(text); }
inline int hello_browser() { return 0; }
#endif"))

#?(:wasm
   (defn emit [line]
     (cpp/hello_emit (cpp/.c_str (cpp/jank.runtime.to_string line))))
   :native
   (defn emit [line] (println line)))

(defn announce []
  (emit #?(:wasm (if (= 1 (cpp/hello_browser)) "platform: browser" "platform: node")
           :native "platform: native")))
