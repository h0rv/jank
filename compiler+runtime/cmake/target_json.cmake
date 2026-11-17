set(jank_target_triple "" CACHE STRING "Target triple for generated AOT configuration")
if(jank_target_triple)
  set(target_triple "${jank_target_triple}")
else()
  separate_arguments(jank_target_cxx_flags NATIVE_COMMAND "${CMAKE_CXX_FLAGS}")
  execute_process(
    COMMAND "${CMAKE_CXX_COMPILER}" ${jank_target_cxx_flags} -print-target-triple
    RESULT_VARIABLE target_triple_result
    OUTPUT_VARIABLE target_triple
    ERROR_VARIABLE target_triple_error
    OUTPUT_STRIP_TRAILING_WHITESPACE)
  if(NOT target_triple_result EQUAL 0 OR target_triple STREQUAL "")
    message(FATAL_ERROR "Failed to query target triple (${target_triple_result}): ${target_triple_error}")
  endif()
endif()

set(jank_lib_linker_flags_list "")

get_target_property(jank_lib_link_dirs_prop jank_common_lib LINK_DIRECTORIES)
foreach(lib ${jank_lib_link_dirs_prop})
  list(APPEND jank_lib_linker_flags_list -L${lib})
endforeach()
list(APPEND jank_lib_linker_flags_list ${jank_linker_flags})
list(APPEND jank_lib_linker_flags_list ${CMAKE_CXX_FLAGS})
list(APPEND jank_lib_linker_flags_list ${CMAKE_SHARED_LINKER_FLAGS})
list(JOIN jank_lib_linker_flags_list " " jank_lib_linker_flags_unescaped)
string(REPLACE "\"" "\\\"" jank_lib_linker_flags_str
               "${jank_lib_linker_flags_unescaped}")

# Build a string of all of our JIT compilation flags so we can load them up in
# the runtime.
set(jank_jit_compile_flags_list ${jank_common_compiler_flags}
                                ${jank_jit_compiler_flags} ${jank_lib_includes})
list(JOIN jank_jit_compile_flags_list " " jank_jit_compile_flags_str_unescaped)
string(REPLACE "\"" "\\\"" jank_jit_compile_flags_str
               "${jank_jit_compile_flags_str_unescaped}")

file(
  GENERATE
  OUTPUT "${CMAKE_BINARY_DIR}/target_config.json"
  CONTENT
    "{
  \"triple\": \"${target_triple}\",
  \"clang_bin\": \"${CMAKE_CXX_COMPILER}\",
  \"jit_flags\": \"${jank_jit_compile_flags_str}\",
  \"aot_flags\": \"${jank_lib_linker_flags_str}\"
}")
