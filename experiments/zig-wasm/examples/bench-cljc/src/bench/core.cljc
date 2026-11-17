;; AI-assisted research benchmark; identical kernels and sizes on every target.
(ns bench.core
  (:require [clojure.string :as string]))

#?(:cljs nil
   :default
   (cpp/raw "#include <chrono>
inline double bench_clock_ms() {
  return std::chrono::duration<double, std::milli>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
}"))

(defn now-ms []
  #?(:cljs (js/performance.now)
     :native (cpp/bench_clock_ms)
     :wasm (cpp/bench_clock_ms)))

(defn fib [n]
  (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))

(defn vector-kernel []
  (reduce + 0.0 (loop [i 0 v []]
                (if (< i 100000) (recur (inc i) (conj v i)) v))))

(defn map-kernel []
  (let [m (loop [i 0 m {}]
            (if (< i 100000) (recur (inc i) (assoc m i (inc i))) m))]
    (loop [i 0 total 0.0]
      (if (< i 100000) (recur (inc i) (+ total (get m i))) total))))

(defn lazy-kernel []
  (reduce + 0.0 (filter even? (map inc (range 100000)))))

(defn string-kernel []
  (count (string/join "," (map #(str "item" %) (range 1000)))))

(defn sort-kernel []
  (reduce + 0.0 (map-indexed (fn [i x] (* (inc i) x))
                         (sort (map #(mod (* % 7919) 5000) (range 5000))))))

(defn timed [f expected]
  (let [start (now-ms)
        result (f)
        elapsed (- (now-ms) start)]
    (if (= expected result)
      elapsed
      (throw (ex-info (str "CHECKSUM FAIL expected=" expected " actual=" result) {})))))

(defn measure [label f expected]
  (let [first-ms (timed f expected)
        samples (loop [i 0 times []]
                  (if (< i 10) (recur (inc i) (conj times (timed f expected))) times))
        ordered (vec (sort samples))
        median (/ (+ (nth ordered 4) (nth ordered 5)) 2.0)]
    (println (str "BENCH " label " checksum=" expected " first-ms=" first-ms
                  " median-ms=" median))
    (println (str "SAMPLES " label " " (string/join "," samples)))))

(defn -main [& _]
  (println (str "ENTRY clock-ms=" (now-ms)))
  (measure "fib27" #(fib 27) 196418)
  (measure "vector100k" vector-kernel 4999950000.0)
  (measure "map100k" map-kernel 5000050000.0)
  (measure "lazy100k" lazy-kernel 2500050000.0)
  (measure "strings1k" string-kernel 7889)
  (measure "sort5k" sort-kernel 41666665000.0)
  (println "BENCH PASS"))

#?(:cljs (set! *main-cli-fn* -main))
