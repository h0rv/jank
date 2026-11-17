(ns jank-test.native-vector-sequence
  (:require [clojure.test :refer [deftest is]]
            [clojure.core-test.portability :as p]))

(deftest sort-traversal
  (let [s (sort (range 5000 0 -1))]
    (is (= (range 1 5001) s))
    (is (= 12502500 (reduce + s)))
    (is (= (range 1 5001) s))
    (is (= (vec (range 1 5001)) (vec s)))
    (is (= (sort (range 1 5001)) s))))

(deftest independent-cursors
  (let [s (sort [3 1 2])
        tail (next s)]
    (is (identical? s (seq s)))
    (is (not (identical? s tail)))
    (is (not (identical? tail (next s))))
    (is (= '(2 3) (rest s) tail))
    (is (identical? tail (seq tail)))
    (is (= '(3) (next tail)))
    (is (= '(1 2 3) s))
    (is (= '(0 1 2 3) (conj s 0)))
    (is (= "(2 3)" (pr-str tail)))
    (is (= (hash '(2 3)) (hash tail)))))

(deftest subsequence-metadata
  (let [s (sort (with-meta [3 1 2] {:source true}))
        tail (next s)
        decorated (with-meta tail {:tail true})]
    (is (= {:source true} (meta s)))
    (is (= '(2 3) decorated))
    (is (= {:tail true} (meta decorated)))
    (is (nil? (meta tail)))
    (is (= {:source true} (meta s)))
    (is (not (identical? tail decorated)))
    (is (= '(3) (next decorated)))
    (is (= '(2 3) tail))
    (is (= '(2 3) (with-meta decorated nil))))
  (is (p/thrown? (with-meta (next (sort [1 2])) 42))))

(deftest sort-by-and-comparators
  (is (= '([1 :b] [1 :d] [2 :a] [2 :c])
         (sort-by first [[2 :a] [1 :b] [2 :c] [1 :d]])))
  (is (= '(3 2 1) (sort-by identity > [1 3 2])))
  (is (= '(3 2 1) (sort > [1 3 2])))
  (is (= '(1 2 3) (sort (sort [3 1 2])))))

(deftest empty-and-singleton
  (doseq [input [nil [] '()]]
    (is (= '() (sort input)))
    (is (nil? (seq (sort input))))
    (is (nil? (next (sort input))))
    (is (= '() (sort-by identity input))))
  (let [s (sort [1])]
    (is (identical? s (seq s)))
    (is (= 1 (first s)))
    (is (= 1 (count s)))
    (is (nil? (next s)))
    (is (= '() (rest s)))
    (is (= {:one true} (meta (with-meta s {:one true}))))
    (is (= '(1) s))))

(deftest interpreter-argument-producer
  (is (= [:a :b :c] (eval '(vector :a :b :c))))
  (is (= 6 (eval '(+ 1 2 3)))))
