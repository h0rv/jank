(ns jank-test.string-join
  (:require [clojure.string :as str]
            [clojure.test :refer [deftest is]]
            [clojure.core-test.portability :as p]))

(deftest empty-and-singleton
  (doseq [coll [nil [] '() (take 0 (range))]]
    (is (= "" (str/join coll)))
    (is (= "" (str/join "," coll))))
  (doseq [separator [nil "," 42 :sep]]
    (is (= "only" (str/join separator ["only"]))))
  (is (= "only" (str/join ["only"]))))

(deftest nil-elements
  (is (= "" (str/join [nil])))
  (is (= "" (str/join "," [nil])))
  (is (= "" (str/join [nil nil])))
  (is (= "," (str/join "," [nil nil])))
  (is (= "x" (str/join [nil "x" nil])))
  (is (= ",x," (str/join "," [nil "x" nil]))))

(deftest element-and-separator-coercion
  (is (= "1true:k[2 3]" (str/join [1 true :k [2 3]])))
  (is (= "1,true,:k,[2 3]" (str/join "," [1 true :k [2 3]])))
  (is (= "ab" (str/join nil ["a" "b"])))
  (is (= "a42b" (str/join 42 ["a" "b"])))
  (is (= "afalseb" (str/join false ["a" "b"])))
  (is (= "a:sepb" (str/join :sep ["a" "b"])))
  (is (= "a[1 2]b" (str/join [1 2] ["a" "b"]))))

(deftest unicode
  (is (= "é東京🙂" (str/join ["é" "東京" "🙂"])))
  (is (= "é🌍東京🌍🙂" (str/join "🌍" ["é" "東京" "🙂"]))))

(deftest lazy-input
  (let [seen (atom [])
        coll (map (fn [x] (swap! seen conj x) x) '(1 2 3))]
    (is (= "1,2,3" (str/join "," coll)))
    (is (= [1 2 3] @seen)))
  (is (= "01234" (str/join (take 5 (range)))))
  (is (= "0,1,2,3,4" (str/join "," (take 5 (range))))))

(deftest invalid-input
  (is (p/thrown? (str/join 42)))
  (is (p/thrown? (str/join "," 42)))
  (is (p/thrown? (str/join "," (map (fn [_] (throw (ex-info "element" {}))) [1])))))
