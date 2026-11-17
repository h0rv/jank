(ns jank-test.integer-range
  (:require [clojure.test :refer [deftest is]]
            [clojure.core-test.portability :as p]))

(defn chunk-values [s]
  (let [c (chunk-first s)]
    (mapv #(nth c %) (range (count c)))))

(deftest chunk-boundaries
  (doseq [n [1 31 32 33 63 64 65 100]
          step [1 -1 3 -3]]
    (let [expected (take n (iterate #(+ % step) 7))
          r (range 7 (+ 7 (* n step)) step)]
      (is (chunked-seq? r))
      (is (= expected r))
      (is (= n (count r)))
      (is (= (vec (take 32 expected)) (chunk-values r)))
      (is (= (drop 32 expected) (chunk-rest r)))
      (is (= (seq (drop 32 expected)) (chunk-next r)))
      (when (> n 1)
        (is (= (drop 33 expected) (chunk-rest (next r)))))
      (is (= (rest expected) (rest r)))
      (is (= expected r)))))

(deftest range-arities-and-empty
  (is (= (range 70) (range 0 70) (range 0 70 1)))
  (doseq [r [(range 0) (range -1) (range 2 2) (range 2 1) (range 1 2 -1)]]
    (is (empty? r))
    (is (nil? (seq r))))
  (is (= [5] (chunk-values (range 5 6))))
  (is (nil? (chunk-next (range 5 6))))
  (is (= '() (chunk-rest (range 5 6))))
  (is (p/thrown? (chunk-first (range 0)))))

(deftest chunked-laziness
  (let [seen (atom [])
        mapped (map (fn [x] (swap! seen conj x) x) (range 100))]
    (is (= [] @seen))
    (is (= 0 (first mapped)))
    (is (= (vec (range 32)) @seen))
    (is (= 32 (nth mapped 32)))
    (is (= (vec (range 64)) @seen)))
  (let [seen (atom 0)]
    (is (= 0 (first (map (fn [x] (swap! seen inc) x) (range)))))
    (is (= 1 @seen)))
  (is (= [0 1 2 3 4] (vec (take 5 (range)))))
  (is (= [7 7 7 7 7] (vec (take 5 (range 7 8 0)))))
  (is (= [7 7 7] (vec (take 3 (range 7 6 0))))))

(deftest pipelines-and-metadata
  (is (= 2550 (reduce + (filter even? (map inc (range 100))))))
  (is (= 0 (reduce (fn [_ x] (reduced x)) nil (range))))
  (let [r (range 1 70)
        tagged (with-meta r {:range true})]
    (is (= {:range true} (meta tagged)))
    (is (= (range 33 70) (chunk-rest tagged)))
    (is (= r tagged))
    (is (nil? (meta r)))))

(deftest other-ranges
  (is (= [0 0.5 1.0 1.5] (vec (range 0 2 0.5))))
  (is (= [2.0 1.5 1.0 0.5] (vec (range 2.0 0.0 -0.5))))
  (is (= [0 1 2] (vec (range 3.0))))
  (is (= [0 1/2 1 3/2] (vec (range 0 2 1/2))))
  (is (= [1.5 1.5 1.5] (vec (take 3 (range 1.5 2.5 0.0))))))

(defn vector-chunks [v]
  (lazy-seq
    (when (seq v)
      (let [n (min 32 (count v))
            b (chunk-buffer n)]
        (dotimes [i n] (chunk-append b (nth v i)))
        (chunk-cons (chunk b) (vector-chunks (vec (drop n v))))))))

(deftest vector-pipeline-laziness
  (let [seen (atom [])
        source (vector-chunks (vec (range 100)))
        mapped (map (fn [x] (swap! seen conj x) (inc x)) source)
        filtered (filter even? mapped)]
    (is (= [] @seen))
    (is (= 2 (first filtered)))
    (is (= (vec (range 32)) @seen))
    (is (= (vec (range 2 101 2)) (vec filtered))))
  (is (= (vec (range 1 71)) (vec (map inc (vec (range 70)))))))

(deftest chunk-tail-realization
  (doseq [advance [next chunk-next]]
    (let [seen (atom 0)
          b (chunk-buffer 1)
          _ (chunk-append b 1)
          tail (lazy-seq (swap! seen inc) (list 2 3))
          s (chunk-cons (chunk b) tail)]
      (is (= 0 @seen))
      (is (identical? tail (rest s)))
      (is (identical? tail (chunk-rest s)))
      (is (= 0 @seen))
      (is (= '(2 3) (advance s)))
      (is (= 1 @seen))))
  (let [b (chunk-buffer 1)
        _ (chunk-append b 1)
        s (chunk-cons (chunk b) (lazy-seq nil))]
    (is (nil? (next s)))
    (is (nil? (chunk-next s))))
  (is (= [0 0.5 1.0 1.5 2.0] (vec (take 5 (map identity (range 0 100 0.5))))))
  (let [b (chunk-buffer 1)
        _ (chunk-append b 1)
        tail (lazy-seq (throw (ex-info "tail" {})))
        s (chunk-cons (chunk b) tail)]
    (is (= 1 (first s)))
    (is (identical? tail (rest s)))
    (is (identical? tail (chunk-rest s)))
    (is (p/thrown? (next s)))))

(deftest chunked-producers
  (let [expected (vec (range 70))
        mapped (map identity (range 70))]
    (is (= expected (vec mapped)))
    (is (= expected (vec mapped)))
    (is (= expected (vec (concat (range 32) (range 32 70)))))
    (is (= expected (vec (keep identity (range 70)))))
    (is (= [99] (vec (filter #(> % 98) (range 100)))))))
