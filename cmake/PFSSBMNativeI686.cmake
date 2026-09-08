if(NOT CMAKE_HOST_SYSTEM_NAME STREQUAL "Linux")
    message(FATAL_ERROR "PFSSBMNativeI686 requires a Linux host")
endif()
if(NOT DEFINED PF_SSBM_I686_SYSROOT)
    message(FATAL_ERROR "set PF_SSBM_I686_SYSROOT to the bootstrapped root")
endif()
get_filename_component(PF_SSBM_I686_SYSROOT "${PF_SSBM_I686_SYSROOT}" ABSOLUTE)
set(
    PF_SSBM_I686_SYSROOT
    "${PF_SSBM_I686_SYSROOT}"
    CACHE PATH
    "Permission-free Linux i686 development sysroot")
list(APPEND CMAKE_TRY_COMPILE_PLATFORM_VARIABLES PF_SSBM_I686_SYSROOT)

set(_pf_i686_lib32 "${PF_SSBM_I686_SYSROOT}/usr/lib32")
set(_pf_i686_gcc "${PF_SSBM_I686_SYSROOT}/usr/lib/gcc/x86_64-linux-gnu/11/32")
foreach(required IN ITEMS
        "${_pf_i686_lib32}/Scrt1.o"
        "${_pf_i686_lib32}/libc.a"
        "${_pf_i686_gcc}/libgcc.a"
        "${_pf_i686_gcc}/libstdc++.a")
    if(NOT EXISTS "${required}")
        message(FATAL_ERROR "incomplete PF_SSBM_I686_SYSROOT: ${required}")
    endif()
endforeach()

set(CMAKE_C_COMPILER gcc CACHE FILEPATH "Linux i686 C compiler")
set(CMAKE_CXX_COMPILER g++ CACHE FILEPATH "Linux i686 C++ compiler")
set(_pf_i686_common
    "-m32 -msse2 -mfpmath=sse -B${_pf_i686_lib32}/ -B${_pf_i686_gcc}/ -isystem ${PF_SSBM_I686_SYSROOT}/usr/include -isystem /usr/include/x86_64-linux-gnu")
set(CMAKE_C_FLAGS_INIT "${_pf_i686_common}")
set(CMAKE_CXX_FLAGS_INIT
    "${_pf_i686_common} -isystem ${PF_SSBM_I686_SYSROOT}/usr/include/x86_64-linux-gnu/c++/11/32")
set(CMAKE_EXE_LINKER_FLAGS_INIT "-m32 -static -B${_pf_i686_lib32}/ -B${_pf_i686_gcc}/")
set(CMAKE_MODULE_LINKER_FLAGS_INIT "-m32 -B${_pf_i686_lib32}/ -B${_pf_i686_gcc}/")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "-m32 -B${_pf_i686_lib32}/ -B${_pf_i686_gcc}/")

unset(_pf_i686_common)
unset(_pf_i686_gcc)
unset(_pf_i686_lib32)
