set(jank_target_sdk_dir "lib/jank/${PROJECT_VERSION}")
if(EMSCRIPTEN)
  set_property(DIRECTORY "${zstd_SOURCE_DIR}/build/cmake" PROPERTY EXCLUDE_FROM_ALL TRUE)
endif()
install(FILES "${CMAKE_BINARY_DIR}/libjank-static-runtime.a"
        DESTINATION "${jank_target_sdk_dir}/lib")
install(FILES "${CMAKE_BINARY_DIR}/target_config.json"
        DESTINATION "${jank_target_sdk_dir}")
install(DIRECTORY "${CMAKE_SOURCE_DIR}/include/cpp/"
        DESTINATION "${jank_target_sdk_dir}/include")

set(jank_target_header_dirs
    third-party/nanobench/include
    third-party/folly
    third-party/bdwgc/include
    third-party/immer
    third-party/zip/src
    third-party/cpptrace/include
    third-party/cppinterop/include
    third-party/cppinterop/lib
    third-party/boost-preprocessor/include
    third-party/boost-multiprecision/include
    third-party/boost-process/include
    third-party/stduuid/include
    third-party/json/include
    third-party/isocline/include)
foreach(dir IN LISTS jank_target_header_dirs)
  install(DIRECTORY "${CMAKE_SOURCE_DIR}/${dir}/"
          DESTINATION "${jank_target_sdk_dir}/include"
          FILES_MATCHING PATTERN "*.h" PATTERN "*.hpp" PATTERN "*.ipp"
                         PATTERN "*.tcc" PATTERN "*.inc")
endforeach()
