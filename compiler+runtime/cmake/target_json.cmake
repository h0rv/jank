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
if(jank_lib_link_dirs_prop)
  foreach(lib ${jank_lib_link_dirs_prop})
    list(APPEND jank_lib_linker_flags_list -L${lib})
  endforeach()
endif()
list(APPEND jank_lib_linker_flags_list ${jank_linker_flags})
separate_arguments(jank_target_link_cxx_flags NATIVE_COMMAND "${CMAKE_CXX_FLAGS}")
separate_arguments(jank_target_shared_link_flags NATIVE_COMMAND "${CMAKE_SHARED_LINKER_FLAGS}")
list(APPEND jank_lib_linker_flags_list ${jank_target_link_cxx_flags} ${jank_target_shared_link_flags})

# Build a string of all of our JIT compilation flags so we can load them up in
# the runtime.
set(jank_jit_compile_flags_list ${jank_common_compiler_flags}
                                ${jank_jit_compiler_flags} ${jank_lib_includes})
if(jank_cross_compile)
  set(jank_host_paths ${LLVM_INCLUDE_DIRS} ${CLANG_INCLUDE_DIRS} ${LLVM_LIBRARY_DIRS}
                      "${llvm_dir}" "${clang_dir}" "${LLVM_INSTALL_PREFIX}"
                      "${CLANG_INSTALL_PREFIX}" "${jank_resource_dir}")
  list(REMOVE_ITEM jank_host_paths "")
  list(REMOVE_DUPLICATES jank_host_paths)

  function(jank_filter_host_flags variable)
    set(filtered "")
    set(path_option "")
    foreach(flag IN LISTS ${variable})
      if(flag MATCHES "^(-I|-L|-isystem|-resource-dir|--sysroot|-isysroot)$")
        list(APPEND filtered ${path_option})
        set(path_option "${flag}")
        continue()
      endif()
      set(host_flag OFF)
      foreach(root IN LISTS jank_host_paths)
        string(REGEX REPLACE "/+$" "" root "${root}")
        string(FIND "${flag}" "${root}" position)
        if(NOT position EQUAL -1)
          string(LENGTH "${root}" length)
          math(EXPR end "${position} + ${length}")
          string(SUBSTRING "${flag}" ${end} -1 suffix)
          if(suffix STREQUAL "" OR suffix MATCHES "^[/\",]")
            set(host_flag ON)
            break()
          endif()
        endif()
      endforeach()
      if(NOT host_flag)
        list(APPEND filtered ${path_option} "${flag}")
      endif()
      set(path_option "")
    endforeach()
    list(APPEND filtered ${path_option})
    set(${variable} "${filtered}" PARENT_SCOPE)
  endfunction()

  jank_filter_host_flags(jank_jit_compile_flags_list)
  jank_filter_host_flags(jank_lib_linker_flags_list)
endif()

list(JOIN jank_lib_linker_flags_list " " jank_lib_linker_flags_unescaped)
string(REPLACE "\"" "\\\"" jank_lib_linker_flags_str
               "${jank_lib_linker_flags_unescaped}")
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
