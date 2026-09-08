function(pf_enable_project_warnings target)
    if(MSVC)
        target_compile_options(
            ${target}
            PRIVATE
                /W4
                /WX
                /permissive-
                /fp:precise)
    elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
        target_compile_options(
            ${target}
            PRIVATE
                -Wall
                -Wextra
                -Wpedantic
                -Werror
                -Wconversion
                -Wformat=2
                -Wmissing-prototypes
                -Wshadow
                -Wstrict-prototypes
                -Wundef
                -Wwrite-strings
                -fno-fast-math
                -ffp-contract=off)
        if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
            target_compile_options(
                ${target}
                PRIVATE
                    -fexcess-precision=standard)
        endif()
    else()
        message(FATAL_ERROR
            "Strict warning policy is not defined for C compiler "
            "${CMAKE_C_COMPILER_ID}")
    endif()
endfunction()

function(pf_enable_cpp_project_warnings target)
    if(MSVC)
        target_compile_options(
            ${target}
            PRIVATE
                /W4
                /WX
                /permissive-
                /fp:precise)
    elseif(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
        target_compile_options(
            ${target}
            PRIVATE
                -Wall
                -Wextra
                -Wpedantic
                -Werror
                -Wconversion
                -Wformat=2
                -Wshadow
                -Wundef
                -fno-fast-math
                -ffp-contract=off)
    else()
        message(FATAL_ERROR
            "Strict warning policy is not defined for C++ compiler "
            "${CMAKE_CXX_COMPILER_ID}")
    endif()
endfunction()
