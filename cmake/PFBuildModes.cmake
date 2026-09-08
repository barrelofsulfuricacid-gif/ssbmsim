function(pf_apply_build_mode target)
    if(PF_ENABLE_SANITIZERS)
        if(MSVC)
            target_compile_options(
                ${target}
                PRIVATE
                    /fsanitize=address
                    /Oy-)
            target_link_options(${target} PRIVATE /INCREMENTAL:NO)
        elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
            target_compile_options(
                ${target}
                PRIVATE
                    -fno-omit-frame-pointer
                    -fsanitize=address,undefined)
            target_link_options(
                ${target}
                PRIVATE
                    -fno-omit-frame-pointer
                    -fsanitize=address,undefined)
        else()
            message(FATAL_ERROR
                "Sanitizer flags are not defined for C compiler "
                "${CMAKE_C_COMPILER_ID}")
        endif()
    endif()

    if(PF_ENABLE_PROFILING)
        target_compile_definitions(${target} PRIVATE PF_PROFILE_BUILD=1)
        if(MSVC)
            target_compile_options(${target} PRIVATE /Oy-)
        elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
            target_compile_options(${target} PRIVATE -fno-omit-frame-pointer)
        else()
            message(FATAL_ERROR
                "Profile flags are not defined for C compiler "
                "${CMAKE_C_COMPILER_ID}")
        endif()
    else()
        target_compile_definitions(${target} PRIVATE PF_PROFILE_BUILD=0)
    endif()
endfunction()
