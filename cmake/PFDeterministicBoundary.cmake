function(pf_assert_deterministic_target target)
    get_target_property(pf_link_libraries ${target} LINK_LIBRARIES)
    if(pf_link_libraries)
        message(FATAL_ERROR
            "The deterministic ${target} target must not link external "
            "libraries: ${pf_link_libraries}")
    endif()

    get_target_property(pf_sources ${target} SOURCES)
    foreach(pf_source IN LISTS pf_sources)
        get_source_file_property(
            pf_source_external "${pf_source}" EXTERNAL_OBJECT)
        if(pf_source_external)
            continue()
        endif()
        if(NOT IS_ABSOLUTE "${pf_source}")
            set(pf_source "${CMAKE_CURRENT_SOURCE_DIR}/${pf_source}")
        endif()

        file(READ "${pf_source}" pf_source_text)
        foreach(pf_forbidden_token IN ITEMS
                "CreateThread"
                "SDL_CreateThread"
                "_beginthread"
                "_beginthreadex"
                "calloc("
                "emscripten_dispatch"
                "fopen("
                "fprintf("
                "free("
                "malloc("
                "mtx_lock"
                "nanosleep("
                "pthread_create"
                "pthread_mutex"
                "printf("
                "realloc("
                "SDL_"
                "Sleep("
                "std::thread"
                "thrd_"
                "time("
                "thrd_create")
            string(FIND
                "${pf_source_text}"
                "${pf_forbidden_token}"
                pf_forbidden_offset)
            if(NOT pf_forbidden_offset EQUAL -1)
                message(FATAL_ERROR
                    "Deterministic target ${target} source ${pf_source} "
                    "contains forbidden thread-creation token "
                    "${pf_forbidden_token}")
            endif()
        endforeach()
    endforeach()
endfunction()
