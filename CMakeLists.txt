cmake_minimum_required(VERSION 4.4)
project(ssbmsim VERSION 0.1.0 DESCRIPTION "Native headless SSBM research simulator" LANGUAGES C CXX)
include(CTest)
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(PFBuildModes)
include(PFProjectWarnings)
include(PFDeterministicBoundary)
option(PF_BUILD_SSBM_RUNTIME "Build the native SSBM runtime" ON)
option(PF_BUILD_SSBM_DECOMP_IMPORT "Compile pinned native gameplay source" ON)
option(PF_ENABLE_SANITIZERS "Enable address and undefined behavior sanitizers" OFF)
option(PF_ENABLE_PROFILING "Preserve frame pointers" OFF)
set(PF_SSBM_DECOMP_SOURCE_DIR "" CACHE PATH "Pinned melee checkout")
set(PF_AURORA_SOURCE_DIR "" CACHE PATH "Pinned patched Aurora checkout")
if(PF_BUILD_SSBM_RUNTIME AND NOT EMSCRIPTEN)
    enable_language(CXX)

    add_library(
        ssbm_runtime
        STATIC
            src/ssbm/article_graphs.cpp
            src/ssbm/article_graphs.h
            src/ssbm/articles.cpp
            src/ssbm/articles.h
            src/ssbm/asset_pack.cpp
            src/ssbm/asset_pack.h
            src/ssbm/effect_particles.cpp
            src/ssbm/effect_particles.h
            src/ssbm/fighter_data.cpp
            src/ssbm/fighter_data.h
            src/ssbm/fighter_actions.cpp
            src/ssbm/fighter_actions.h
            src/ssbm/fighter_dynamics.cpp
            src/ssbm/fighter_dynamics.h
            src/ssbm/fighter_geometry.cpp
            src/ssbm/fighter_geometry.h
            src/ssbm/joint_trees.cpp
            src/ssbm/joint_trees.h
            src/ssbm/native_effect_banks.cpp
            src/ssbm/native_effect_banks.h
            src/ssbm/native_compat/native_effect_bank_api.h
            src/ssbm/native_item_common.cpp
            src/ssbm/native_item_common.h
            src/ssbm/native_compat/native_archive_root_api.h
            src/ssbm/native_compat/native_fighter_common_api.h
            src/ssbm/native_compat/native_item_common_api.h
            src/ssbm/native_player_common.cpp
            src/ssbm/native_player_common.h
            src/ssbm/native_compat/native_player_common_api.h
            src/ssbm/native_stage_assets.cpp
            src/ssbm/native_stage_assets.h
            src/ssbm/native_compat/native_stage_assets_api.h
            src/ssbm/player_common.cpp
            src/ssbm/player_common.h
            src/ssbm/stage_collision.cpp
            src/ssbm/stage_collision.h
            src/ssbm/stage_ground_params.cpp
            src/ssbm/stage_ground_params.h
            src/ssbm/stage_joint_animations.cpp
            src/ssbm/stage_joint_animations.h
            src/ssbm/stage_map_heads.cpp
            src/ssbm/stage_map_heads.h
            src/ssbm/runtime.cpp
            src/ssbm/runtime.h
            src/ssbm/source_catalog.cpp
            src/ssbm/source_catalog.h
            src/ssbm/source_graphs.cpp
            src/ssbm/source_graphs.h)
    target_include_directories(
        ssbm_runtime
        PUBLIC
            "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm>")
    target_compile_features(ssbm_runtime PUBLIC cxx_std_20)
    set_target_properties(
        ssbm_runtime
        PROPERTIES
            CXX_EXTENSIONS OFF)
    pf_enable_cpp_project_warnings(ssbm_runtime)
    pf_apply_build_mode(ssbm_runtime)
    pf_assert_deterministic_target(ssbm_runtime)

    add_library(
        ssbm_pack_file
        STATIC
            src/ssbm/mapped_pack.cpp
            src/ssbm/mapped_pack.h)
    target_link_libraries(ssbm_pack_file PUBLIC ssbm_runtime)
    if(UNIX AND NOT APPLE)
        target_compile_definitions(ssbm_pack_file PRIVATE _FILE_OFFSET_BITS=64)
    endif()
    target_compile_features(ssbm_pack_file PUBLIC cxx_std_20)
    set_target_properties(
        ssbm_pack_file
        PROPERTIES
            CXX_EXTENSIONS OFF)
    pf_enable_cpp_project_warnings(ssbm_pack_file)
    pf_apply_build_mode(ssbm_pack_file)

    add_executable(
        ssbm_native_replay_runner
        src/tools/ssbm_native_replay_runner.cpp)
    target_link_libraries(ssbm_native_replay_runner PRIVATE ssbm_pack_file)
    target_compile_features(ssbm_native_replay_runner PRIVATE cxx_std_20)
    set_target_properties(
        ssbm_native_replay_runner
        PROPERTIES
            CXX_EXTENSIONS OFF)
    pf_enable_cpp_project_warnings(ssbm_native_replay_runner)
    pf_apply_build_mode(ssbm_native_replay_runner)

    add_executable(
        ssbm_runtime_test
        tests/ssbm/test_native_runtime.cpp)
    target_link_libraries(ssbm_runtime_test PRIVATE ssbm_runtime)
    target_compile_features(ssbm_runtime_test PRIVATE cxx_std_20)
    set_target_properties(
        ssbm_runtime_test
        PROPERTIES
            CXX_EXTENSIONS OFF)
    pf_enable_cpp_project_warnings(ssbm_runtime_test)
    pf_apply_build_mode(ssbm_runtime_test)
    add_test(NAME ssbm.incomplete_pack_rejected COMMAND ssbm_runtime_test)
    set_tests_properties(
        ssbm.incomplete_pack_rejected
        PROPERTIES
            PASS_REGULAR_EXPRESSION "ssbm-runtime=pass")

    add_executable(
        ssbm_effect_pack_test
        tests/ssbm/test_effect_pack.cpp)
    target_link_libraries(ssbm_effect_pack_test PRIVATE ssbm_pack_file)
    target_compile_features(ssbm_effect_pack_test PRIVATE cxx_std_20)
    set_target_properties(
        ssbm_effect_pack_test
        PROPERTIES
            CXX_EXTENSIONS OFF)
    pf_enable_cpp_project_warnings(ssbm_effect_pack_test)
    pf_apply_build_mode(ssbm_effect_pack_test)

    add_executable(
        ssbm_stage_ground_param_pack_test
        tests/ssbm/test_stage_ground_param_pack.cpp)
    target_link_libraries(ssbm_stage_ground_param_pack_test PRIVATE ssbm_pack_file)
    target_compile_features(ssbm_stage_ground_param_pack_test PRIVATE cxx_std_20)
    set_target_properties(
        ssbm_stage_ground_param_pack_test
        PROPERTIES
            CXX_EXTENSIONS OFF)
    pf_enable_cpp_project_warnings(ssbm_stage_ground_param_pack_test)
    pf_apply_build_mode(ssbm_stage_ground_param_pack_test)

    add_executable(
        ssbm_stage_map_head_pack_test
        tests/ssbm/test_stage_map_head_pack.cpp)
    target_link_libraries(ssbm_stage_map_head_pack_test PRIVATE ssbm_pack_file)
    target_compile_features(ssbm_stage_map_head_pack_test PRIVATE cxx_std_20)
    set_target_properties(
        ssbm_stage_map_head_pack_test
        PROPERTIES
            CXX_EXTENSIONS OFF)
    pf_enable_cpp_project_warnings(ssbm_stage_map_head_pack_test)
    pf_apply_build_mode(ssbm_stage_map_head_pack_test)

    add_executable(
        ssbm_stage_joint_animation_pack_test
        tests/ssbm/test_stage_joint_animation_pack.cpp)
    target_link_libraries(
        ssbm_stage_joint_animation_pack_test PRIVATE ssbm_pack_file)
    target_compile_features(
        ssbm_stage_joint_animation_pack_test PRIVATE cxx_std_20)
    set_target_properties(
        ssbm_stage_joint_animation_pack_test
        PROPERTIES
            CXX_EXTENSIONS OFF)
    pf_enable_cpp_project_warnings(ssbm_stage_joint_animation_pack_test)
    pf_apply_build_mode(ssbm_stage_joint_animation_pack_test)

    add_executable(
        ssbm_player_common_pack_test
        tests/ssbm/test_player_common_pack.cpp)
    target_link_libraries(ssbm_player_common_pack_test PRIVATE ssbm_pack_file)
    target_compile_features(ssbm_player_common_pack_test PRIVATE cxx_std_20)
    set_target_properties(
        ssbm_player_common_pack_test
        PROPERTIES
            CXX_EXTENSIONS OFF)
    pf_enable_cpp_project_warnings(ssbm_player_common_pack_test)
    pf_apply_build_mode(ssbm_player_common_pack_test)

    if(PF_BUILD_SSBM_DECOMP_IMPORT)
        find_package(Python3 REQUIRED COMPONENTS Interpreter)
        if(NOT EXISTS "${PF_SSBM_DECOMP_SOURCE_DIR}/.git")
            message(FATAL_ERROR
                "PF_SSBM_DECOMP_SOURCE_DIR must be a pinned melee checkout")
        endif()
        if(NOT EXISTS "${PF_AURORA_SOURCE_DIR}/.git")
            message(FATAL_ERROR
                "PF_AURORA_SOURCE_DIR must be a pinned Aurora checkout")
        endif()
        set(
            PF_SSBM_NATIVE_IMPORT_DIR
            "${CMAKE_CURRENT_BINARY_DIR}/ssbm-native-import")
        file(
            GLOB PF_SSBM_NATIVE_ADAPTATION_SPECS
            CONFIGURE_DEPENDS
            "${CMAKE_CURRENT_SOURCE_DIR}/tools/host_adaptations/*.json")
        set_property(
            DIRECTORY
            APPEND
            PROPERTY CMAKE_CONFIGURE_DEPENDS
                "${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat/platform.h"
                "${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat/target_bool.h"
                "${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat/native_msl_math.h"
                "${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat/native_numeric.h"
                "${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat/native_ps_math.h"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/apply_source_adaptation.py"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/build_ssbm_source_manifest.py"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_ssbm_native_import.py"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_import.json"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_source_readiness.json"
                ${PF_SSBM_NATIVE_ADAPTATION_SPECS})
        execute_process(
            COMMAND
                "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_ssbm_native_import.py"
                --decomp "${PF_SSBM_DECOMP_SOURCE_DIR}"
                --aurora "${PF_AURORA_SOURCE_DIR}"
                --spec "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_import.json"
                --readiness "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_source_readiness.json"
                --compat "${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat"
                --output-cmake "${PF_SSBM_NATIVE_IMPORT_DIR}/sources.cmake"
                --output-manifest "${PF_SSBM_NATIVE_IMPORT_DIR}/manifest.json"
            RESULT_VARIABLE PF_SSBM_NATIVE_IMPORT_RESULT
            OUTPUT_VARIABLE PF_SSBM_NATIVE_IMPORT_OUTPUT
            ERROR_VARIABLE PF_SSBM_NATIVE_IMPORT_ERROR)
        if(NOT PF_SSBM_NATIVE_IMPORT_RESULT EQUAL 0)
            message(FATAL_ERROR
                "native doldecomp import failed:\n"
                "${PF_SSBM_NATIVE_IMPORT_OUTPUT}${PF_SSBM_NATIVE_IMPORT_ERROR}")
        endif()
        string(STRIP "${PF_SSBM_NATIVE_IMPORT_OUTPUT}" PF_SSBM_NATIVE_IMPORT_OUTPUT)
        message(STATUS "${PF_SSBM_NATIVE_IMPORT_OUTPUT}")
        include("${PF_SSBM_NATIVE_IMPORT_DIR}/sources.cmake")
        foreach(unit_id IN LISTS PF_SSBM_NATIVE_ADAPTED_SOURCE_IDS)
            set_property(
                SOURCE "${PF_SSBM_NATIVE_ADAPTED_SOURCE_${unit_id}}"
                APPEND
                PROPERTY INCLUDE_DIRECTORIES
                    "${PF_SSBM_NATIVE_ADAPTED_INCLUDE_DIR_${unit_id}}")
        endforeach()
        set(
            PF_SSBM_NATIVE_SOURCE_MANIFEST
            "${PF_SSBM_NATIVE_IMPORT_DIR}/source_manifest.json")
        execute_process(
            COMMAND
                "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/build_ssbm_source_manifest.py"
                --decomp "${PF_SSBM_DECOMP_SOURCE_DIR}"
                --revision "${PF_SSBM_DECOMP_REVISION}"
                --readiness "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_source_readiness.json"
                --import-spec "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_import.json"
                --output "${PF_SSBM_NATIVE_SOURCE_MANIFEST}"
            RESULT_VARIABLE PF_SSBM_SOURCE_MANIFEST_RESULT
            OUTPUT_VARIABLE PF_SSBM_SOURCE_MANIFEST_OUTPUT
            ERROR_VARIABLE PF_SSBM_SOURCE_MANIFEST_ERROR)
        if(NOT PF_SSBM_SOURCE_MANIFEST_RESULT EQUAL 0)
            message(FATAL_ERROR
                "native source-manifest generation failed:\n"
                "${PF_SSBM_SOURCE_MANIFEST_OUTPUT}${PF_SSBM_SOURCE_MANIFEST_ERROR}")
        endif()
        string(
            STRIP
            "${PF_SSBM_SOURCE_MANIFEST_OUTPUT}"
            PF_SSBM_SOURCE_MANIFEST_OUTPUT)
        message(STATUS "${PF_SSBM_SOURCE_MANIFEST_OUTPUT}")

        function(pf_configure_ssbm_decomp_target target enforce_runtime_boundary)
            target_include_directories(
                ${target}
                PUBLIC
                    "${PF_SSBM_NATIVE_ADAPTED_HEADER_INCLUDE_DIR}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat"
                    "${PF_AURORA_SOURCE_DIR}/include"
                    "${PF_SSBM_DECOMP_SOURCE_DIR}/src"
                    "${PF_SSBM_DECOMP_SOURCE_DIR}/src/melee"
                    "${PF_SSBM_DECOMP_SOURCE_DIR}/src/melee/ft/kinds"
                    "${PF_SSBM_DECOMP_SOURCE_DIR}/src/Runtime"
                    "${PF_SSBM_DECOMP_SOURCE_DIR}/src/sysdolphin"
                    "${PF_SSBM_DECOMP_SOURCE_DIR}/extern/dolphin/include")
            target_compile_definitions(
                ${target}
                PUBLIC
                    DEBUG=0
                    LINT=1
                    TARGET_PC=1)
            target_compile_features(${target} PUBLIC c_std_17)
            set_target_properties(${target} PROPERTIES C_EXTENSIONS OFF)
            pf_enable_project_warnings(${target})
            if(MSVC)
                target_compile_options(${target} PRIVATE /wd4245)
                if(NOT enforce_runtime_boundary)
                    target_compile_options(
                        ${target}
                        PRIVATE
                            "/FI${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat/target_bool.h")
                endif()
                foreach(header IN LISTS PF_SSBM_NATIVE_FORCED_HEADERS)
                    target_compile_options(${target} PRIVATE "/FI${header}")
                endforeach()
            elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
                if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND
                        CMAKE_SIZEOF_VOID_P EQUAL 4 AND
                        CMAKE_C_COMPILER_ID STREQUAL "GNU")
                    # GALE01 aggregates align double and 64-bit integer fields
                    # to eight bytes. Keep this on gameplay C targets; native
                    # C++ retains its system-library ABI and explicit C API layouts.
                    target_compile_options(${target} PRIVATE
                        "$<$<COMPILE_LANGUAGE:C>:-malign-double>")
                endif()
                # Establish the native host boundary before any upstream
                # header can include Aurora's platform-sensitive types.h.
                if(NOT enforce_runtime_boundary)
                    target_compile_options(
                        ${target}
                        PRIVATE
                            "SHELL:-include ${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat/target_bool.h")
                endif()
                target_compile_options(
                    ${target}
                    PRIVATE
                        "SHELL:-include ${CMAKE_CURRENT_SOURCE_DIR}/src/ssbm/native_compat/platform.h"
                        -fno-strict-aliasing
                        -fno-builtin-sinf
                        -fno-builtin-cosf
                        -Wno-absolute-value
                        -Wno-address
                        -Wno-array-bounds
                        -Wno-bool-compare
                        -Wno-bool-operation
                        -Wno-conversion
                        -Wno-discarded-qualifiers
                        -Wno-enum-conversion
                        -Wno-implicit-fallthrough
                        -Wno-int-in-bool-context
                        -Wno-maybe-uninitialized
                        -Wno-missing-braces
                        -Wno-missing-field-initializers
                        -Wno-missing-prototypes
                        -Wno-old-style-declaration
                        -Wno-pedantic
                        -Wno-pointer-compare
                        -Wno-shadow
                        -Wno-sign-compare
                        -Wno-sign-conversion
                        -Wno-strict-prototypes
                        -Wundef
                        -Wno-unused-but-set-variable
                        -Wno-unused-function
                        -Wno-unused-parameter
                        -Wno-unused-value
                        -Wno-unused-variable
                        -Wno-unknown-pragmas)
                if(UNIX)
                    # glibc's math.h declares internal __fabs* entry points.
                    # Melee's placeholder.h defines __fabs as a macro, so the
                    # system headers must be parsed before an adapted Melee
                    # header is force-included.
                    target_compile_options(
                        ${target}
                        PRIVATE
                            "SHELL:-include math.h"
                            "SHELL:-include stdarg.h"
                            "SHELL:-include sys/types.h")
                endif()
                foreach(header IN LISTS PF_SSBM_NATIVE_FORCED_HEADERS)
                    target_compile_options(
                        ${target} PRIVATE "SHELL:-include ${header}")
                endforeach()
            endif()
            pf_apply_build_mode(${target})
            if(enforce_runtime_boundary)
                pf_assert_deterministic_target(${target})
            endif()
        endfunction()

        add_library(
            ssbm_decomp_compile_ready
            OBJECT
            EXCLUDE_FROM_ALL
                ${PF_SSBM_NATIVE_COMPILE_READY_SOURCES})
        if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
            foreach(unit_id IN LISTS PF_SSBM_NATIVE_SOURCE_COMPILE_OPTION_IDS)
                set_source_files_properties(
                    "${PF_SSBM_NATIVE_SOURCE_COMPILE_SOURCE_${unit_id}}"
                    PROPERTIES
                        COMPILE_OPTIONS
                            "${PF_SSBM_NATIVE_SOURCE_COMPILE_OPTIONS_${unit_id}}")
            endforeach()
            foreach(unit_id IN LISTS PF_SSBM_NATIVE_SCOPED_HEADER_SOURCE_IDS)
                foreach(header IN LISTS PF_SSBM_NATIVE_SCOPED_HEADERS_${unit_id})
                    set_property(
                        SOURCE
                            "${PF_SSBM_NATIVE_SCOPED_HEADER_SOURCE_${unit_id}}"
                        APPEND
                        PROPERTY COMPILE_OPTIONS -include "${header}")
                endforeach()
            endforeach()
        endif()
        pf_configure_ssbm_decomp_target(ssbm_decomp_compile_ready FALSE)
        if(MSVC)
            target_compile_options(ssbm_decomp_compile_ready PRIVATE /Gy /Gw)
        elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
            target_compile_options(
                ssbm_decomp_compile_ready
                PRIVATE -ffunction-sections -fdata-sections)
            if(CMAKE_C_COMPILER_ID STREQUAL "GNU")
                # The compile-ready target is an analysis inventory. These
                # diagnostics remain enabled for every runtime-selected slice.
                target_compile_options(
                    ssbm_decomp_compile_ready
                    PRIVATE
                        -Wno-cast-function-type
                        -Wno-format-overflow
                        # gmregclear.c models an original adjacent-BSS overlay
                        # with a zero-length tail array. GCC 13 diagnoses the
                        # source's documented +0x6BC accesses as object overflow.
                        "$<$<C_COMPILER_ID:GNU>:-Wno-error=stringop-overflow>")
            endif()
        endif()

        set(
            PF_SSBM_NATIVE_PROVIDER_OBJECTS
            "$<TARGET_OBJECTS:ssbm_decomp_compile_ready>")
        if(PF_SSBM_NATIVE_ADAPTED_PROVIDER_SOURCES)
            add_library(
                ssbm_decomp_adapted_providers
                OBJECT
                EXCLUDE_FROM_ALL
                    ${PF_SSBM_NATIVE_ADAPTED_PROVIDER_SOURCES})
            pf_configure_ssbm_decomp_target(
                ssbm_decomp_adapted_providers FALSE)
            if(MSVC)
                target_compile_options(
                    ssbm_decomp_adapted_providers PRIVATE /Gy /Gw)
            elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
                target_compile_options(
                    ssbm_decomp_adapted_providers
                    PRIVATE
                        -ffunction-sections
                        -fdata-sections
                        # See the compile-ready inventory note above. This
                        # provider is retained for transitive symbols, not the
                        # noncompetitive record-clear mode that owns the overlay.
                        "$<$<C_COMPILER_ID:GNU>:-Wno-error=stringop-overflow>")
            endif()
            list(
                APPEND
                PF_SSBM_NATIVE_PROVIDER_OBJECTS
                "$<TARGET_OBJECTS:ssbm_decomp_adapted_providers>")
        endif()

        add_library(
            ssbm_native_host_providers
            OBJECT
                src/ssbm/native_compat/native_arithmetic.c
                src/ssbm/native_compat/native_archive_public.c
                src/ssbm/native_compat/native_debug.c
                src/ssbm/native_compat/native_competitive_presentation.c
                src/ssbm/native_compat/native_gobj_runtime.c
                src/ssbm/native_compat/native_gobj_step.c
                src/ssbm/native_compat/native_gx_texture.c
                src/ssbm/native_compat/native_gx_viewport.c
                src/ssbm/native_compat/native_texture_tables.c
                src/ssbm/native_compat/native_match_setup.c
                src/ssbm/native_compat/native_memory.c
                src/ssbm/native_compat/native_fighter_state.c
                src/ssbm/native_compat/native_pad_input.c
                src/ssbm/native_compat/native_rng.c
                src/ssbm/native_compat/native_slippi.c
                src/ssbm/native_compat/native_slippi_spawn.c
                src/ssbm/native_compat/native_fd_scene.c
                src/ssbm/native_compat/native_slippi_frame_start.c
                src/ssbm/native_compat/native_objalloc.c)
        pf_configure_ssbm_decomp_target(ssbm_native_host_providers TRUE)
        add_library(
            ssbm_native_fail_closed_boundary_objects
            OBJECT
                src/ssbm/native_compat/native_fail_closed_boundaries.c
                src/ssbm/native_compat/native_fail_closed_boundaries.h)
        if(MSVC)
            target_compile_options(
                ssbm_native_host_providers PRIVATE /Gy)
            target_compile_options(
                ssbm_native_fail_closed_boundary_objects PRIVATE /Gy)
        elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
            target_compile_options(
                ssbm_native_host_providers
                PRIVATE -ffunction-sections -fdata-sections)
            target_compile_options(
                ssbm_native_fail_closed_boundary_objects
                PRIVATE -ffunction-sections -fdata-sections)
        endif()
        set(
            PF_SSBM_NATIVE_EXTERNAL_PROVIDER_OBJECTS
            "$<TARGET_OBJECTS:ssbm_native_host_providers>"
            "$<TARGET_OBJECTS:ssbm_native_fail_closed_boundary_objects>")
        set(
            PF_SSBM_NATIVE_EXTERNAL_PROVIDER_OBJECT_LIST
            "${PF_SSBM_NATIVE_IMPORT_DIR}/objects/$<CONFIG>/native-host-providers.txt")
        file(
            GENERATE
            OUTPUT "${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_OBJECT_LIST}"
            CONTENT "$<JOIN:${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_OBJECTS},\n>\n")
        set(
            PF_SSBM_NATIVE_EXTERNAL_PROVIDER_TOPOLOGY
            "${PF_SSBM_NATIVE_IMPORT_DIR}/objects/$<CONFIG>/native-host-provider-topology.json")
        add_custom_command(
            OUTPUT "${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_TOPOLOGY}"
            COMMAND
                "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/write_native_provider_topology.py"
                --object-list
                "${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_OBJECT_LIST}"
                --nm "${CMAKE_NM}"
                --output "${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_TOPOLOGY}"
            DEPENDS
                ${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_OBJECTS}
                "${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_OBJECT_LIST}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/plan_native_root_closure.py"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/write_native_provider_topology.py"
            COMMAND_EXPAND_LISTS
            COMMENT "Fingerprinting native host-provider symbol topology"
            VERBATIM)

        foreach(tool_variable IN ITEMS
                CMAKE_AR
                CMAKE_LINKER
                CMAKE_NM
                CMAKE_OBJCOPY
                CMAKE_OBJDUMP)
            if(NOT DEFINED ${tool_variable} OR "${${tool_variable}}" STREQUAL "")
                message(FATAL_ERROR
                    "native root-closure import requires ${tool_variable}")
            endif()
        endforeach()
        set(
            PF_SSBM_NATIVE_PROVIDER_OBJECT_LIST
            "${PF_SSBM_NATIVE_IMPORT_DIR}/objects/$<CONFIG>/compile-ready.txt")
        file(
            GENERATE
            OUTPUT "${PF_SSBM_NATIVE_PROVIDER_OBJECT_LIST}"
            CONTENT "$<JOIN:${PF_SSBM_NATIVE_PROVIDER_OBJECTS},\n>\n")

        set(PF_SSBM_NATIVE_ROOT_CLOSURE_ARCHIVES)
        set(PF_SSBM_NATIVE_ROOT_CLOSURE_TARGETS)
        set(PF_SSBM_NATIVE_LINKER_ARGUMENTS)
        if(UNIX AND CMAKE_SIZEOF_VOID_P EQUAL 4)
            list(
                APPEND
                PF_SSBM_NATIVE_LINKER_ARGUMENTS
                --linker-argument=-m
                --linker-argument=elf_i386)
        endif()
        foreach(unit_id IN LISTS PF_SSBM_NATIVE_ROOTED_UNIT_IDS)
            set(rooted_target "ssbm_decomp_root_${unit_id}")
            set(source_variable "PF_SSBM_NATIVE_ROOTED_SOURCE_${unit_id}")
            set(source_path_variable "PF_SSBM_NATIVE_ROOTED_PATH_${unit_id}")
            set(roots_variable "PF_SSBM_NATIVE_ROOTED_ROOTS_${unit_id}")
            add_library(
                ${rooted_target}
                OBJECT
                    "${${source_variable}}")
            pf_configure_ssbm_decomp_target(${rooted_target} FALSE)
            if(MSVC)
                target_compile_options(${rooted_target} PRIVATE /Gy /Gw)
            elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
                target_compile_options(
                    ${rooted_target} PRIVATE -ffunction-sections -fdata-sections)
            endif()

            set(root_arguments)
            foreach(root_symbol IN LISTS ${roots_variable})
                list(APPEND root_arguments --root "${root_symbol}")
            endforeach()
            set(
                root_closure_directory
                "${PF_SSBM_NATIVE_IMPORT_DIR}/rooted/$<CONFIG>/${unit_id}")
            set(
                root_closure_plan
                "${root_closure_directory}/plan.json")
            set(
                root_closure_archive
                "${root_closure_directory}/${CMAKE_STATIC_LIBRARY_PREFIX}${unit_id}${CMAKE_STATIC_LIBRARY_SUFFIX}")
            set(
                root_closure_manifest
                "${root_closure_directory}/manifest.json")
            add_custom_command(
                OUTPUT
                    "${root_closure_plan}"
                    "${root_closure_archive}"
                    "${root_closure_manifest}"
                COMMAND
                    "${CMAKE_COMMAND}" -E make_directory
                    "${root_closure_directory}"
                COMMAND
                    "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/plan_native_root_closure.py"
                    --readiness "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_source_readiness.json"
                    --source-manifest "${PF_SSBM_NATIVE_SOURCE_MANIFEST}"
                    --import-spec "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_import.json"
                    --object-list "${PF_SSBM_NATIVE_PROVIDER_OBJECT_LIST}"
                    --root-object "$<TARGET_OBJECTS:${rooted_target}>"
                    --root-source "${${source_path_variable}}"
                    ${root_arguments}
                    ${PF_SSBM_NATIVE_PROVIDER_ROOT_ARGUMENTS}
                    --external-provider-object-list
                    "${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_OBJECT_LIST}"
                    --output "${root_closure_plan}"
                    --nm "${CMAKE_NM}"
                    --objdump "${CMAKE_OBJDUMP}"
                COMMAND
                    "${Python3_EXECUTABLE}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/materialize_native_root_closure.py"
                    --plan "${root_closure_plan}"
                    --readiness "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_source_readiness.json"
                    --source-manifest "${PF_SSBM_NATIVE_SOURCE_MANIFEST}"
                    --import-spec "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_import.json"
                    --object-list "${PF_SSBM_NATIVE_PROVIDER_OBJECT_LIST}"
                    --root-source "${${source_path_variable}}"
                    --root-object "$<TARGET_OBJECTS:${rooted_target}>"
                    --output-archive "${root_closure_archive}"
                    --output-manifest "${root_closure_manifest}"
                    --objdump "${CMAKE_OBJDUMP}"
                    --objcopy "${CMAKE_OBJCOPY}"
                    --linker "${CMAKE_LINKER}"
                    ${PF_SSBM_NATIVE_LINKER_ARGUMENTS}
                    # Melee's Runtime/__mem.c intentionally gives memcpy
                    # overlap-safe behavior. Rename definitions and every
                    # selected relocation in the sliced archive so that exact
                    # source behavior does not collide with static host libc.
                    --redefine-symbol memcpy=pf_ssbm_memcpy
                    --redefine-symbol memset=pf_ssbm_memset
                    --ar "${CMAKE_AR}"
                    --nm "${CMAKE_NM}"
                DEPENDS
                    ${PF_SSBM_NATIVE_PROVIDER_OBJECTS}
                    $<TARGET_OBJECTS:${rooted_target}>
                    "${PF_SSBM_NATIVE_PROVIDER_OBJECT_LIST}"
                    "${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_OBJECT_LIST}"
                    "${PF_SSBM_NATIVE_EXTERNAL_PROVIDER_TOPOLOGY}"
                    "${PF_SSBM_NATIVE_SOURCE_MANIFEST}"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/analyze_native_link_closure.py"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/materialize_native_root_closure.py"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/plan_native_root_closure.py"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/slice_native_object.py"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_import.json"
                    "${CMAKE_CURRENT_SOURCE_DIR}/tools/ssbm_native_source_readiness.json"
                COMMAND_EXPAND_LISTS
                COMMENT "Materializing native source closure for ${unit_id}"
                VERBATIM)
            set(root_closure_target "ssbm_decomp_root_closure_${unit_id}")
            add_custom_target(
                ${root_closure_target}
                DEPENDS
                    "${root_closure_plan}"
                    "${root_closure_archive}"
                    "${root_closure_manifest}")
            add_dependencies(
                ${root_closure_target}
                ssbm_decomp_compile_ready
                ${rooted_target})
            if(TARGET ssbm_decomp_adapted_providers)
                add_dependencies(
                    ${root_closure_target}
                    ssbm_decomp_adapted_providers)
            endif()
            add_dependencies(
                ${root_closure_target}
                ssbm_native_host_providers
                ssbm_native_fail_closed_boundary_objects)
            list(
                APPEND
                PF_SSBM_NATIVE_ROOT_CLOSURE_ARCHIVES
                "${root_closure_archive}")
            list(
                APPEND
                PF_SSBM_NATIVE_ROOT_CLOSURE_TARGETS
                ${root_closure_target})
        endforeach()

        add_library(
            ssbm_native_fail_closed_boundaries
            STATIC
                $<TARGET_OBJECTS:ssbm_native_fail_closed_boundary_objects>)
        add_library(
            ssbm_native_host_provider_library
            STATIC
                $<TARGET_OBJECTS:ssbm_native_host_providers>)

        add_library(
            ssbm_decomp_direct_import
            STATIC
                ${PF_SSBM_NATIVE_DECOMP_SOURCES}
                src/ssbm/native_compat/native_gobj_runtime.h
                src/ssbm/native_compat/native_match_setup.h
                src/ssbm/native_compat/native_memory.h
                src/ssbm/native_compat/native_objalloc.h)
        pf_configure_ssbm_decomp_target(ssbm_decomp_direct_import TRUE)
        target_compile_definitions(
            ssbm_decomp_direct_import
            PRIVATE
                memcpy=pf_ssbm_memcpy
                memset=pf_ssbm_memset)
        add_library(ssbm_decomp_import INTERFACE)
        if(PF_SSBM_NATIVE_ROOT_CLOSURE_TARGETS)
            add_dependencies(
                ssbm_decomp_import
                ${PF_SSBM_NATIVE_ROOT_CLOSURE_TARGETS})
            set(
                PF_SSBM_NATIVE_ROOT_LINK_GROUP
                ${PF_SSBM_NATIVE_ROOT_CLOSURE_ARCHIVES}
                ssbm_decomp_direct_import
                ssbm_native_host_provider_library)
            string(
                JOIN ","
                PF_SSBM_NATIVE_ROOT_LINK_GROUP_ARGUMENT
                ${PF_SSBM_NATIVE_ROOT_LINK_GROUP})
            target_link_libraries(
                ssbm_decomp_import
                INTERFACE
                    "$<LINK_GROUP:RESCAN,${PF_SSBM_NATIVE_ROOT_LINK_GROUP_ARGUMENT}>")

            add_library(ssbm_rooted_match_import INTERFACE)
            add_dependencies(
                ssbm_rooted_match_import
                ${PF_SSBM_NATIVE_ROOT_CLOSURE_TARGETS})
            set(
                PF_SSBM_ROOTED_MATCH_LINK_GROUP
                ${PF_SSBM_NATIVE_ROOT_CLOSURE_ARCHIVES}
                ssbm_native_host_provider_library)
            string(
                JOIN ","
                PF_SSBM_ROOTED_MATCH_LINK_GROUP_ARGUMENT
                ${PF_SSBM_ROOTED_MATCH_LINK_GROUP})
            target_link_libraries(
                ssbm_rooted_match_import
                INTERFACE
                    "$<LINK_GROUP:RESCAN,${PF_SSBM_ROOTED_MATCH_LINK_GROUP_ARGUMENT}>"
                    ssbm_native_fail_closed_boundaries)
            if(UNIX)
                target_link_libraries(ssbm_rooted_match_import INTERFACE m)
            endif()
        else()
            target_link_libraries(
                ssbm_decomp_import
                INTERFACE
                    ssbm_decomp_direct_import
                    ssbm_native_host_provider_library)
        endif()
        if(UNIX)
            target_link_libraries(ssbm_decomp_import INTERFACE m)
        endif()
        target_link_libraries(
            ssbm_decomp_import
            INTERFACE ssbm_native_fail_closed_boundaries)
        if(TARGET ssbm_rooted_match_import)
            target_link_libraries(ssbm_runtime PUBLIC ssbm_rooted_match_import)
        else()
            target_link_libraries(ssbm_runtime PUBLIC ssbm_decomp_import)
        endif()
        if(MSVC)
            target_compile_options(ssbm_decomp_direct_import PRIVATE /Gy)
        elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
            target_compile_options(
                ssbm_decomp_direct_import
                PRIVATE -ffunction-sections -fdata-sections)
        endif()

        add_executable(
            ssbm_decomp_import_test
            tests/ssbm/test_native_decomp.c)
        # These source-link tests do not call runtime startup, but imported
        # functions still reference its asset providers. Include those providers
        # explicitly, as the real runner does during startup.
        target_link_libraries(ssbm_decomp_import_test PRIVATE ssbm_decomp_import
            "$<LINK_LIBRARY:WHOLE_ARCHIVE,ssbm_runtime>")
        pf_configure_ssbm_decomp_target(ssbm_decomp_import_test FALSE)
        add_test(NAME ssbm.decomp_import COMMAND ssbm_decomp_import_test)
        set_tests_properties(
            ssbm.decomp_import
            PROPERTIES
                PASS_REGULAR_EXPRESSION "ssbm-decomp-import=pass")

        add_executable(
            ssbm_match_root_link_test
            tests/ssbm/test_native_match_root_link.c)
        target_link_libraries(
            ssbm_match_root_link_test
            PRIVATE ssbm_decomp_import "$<LINK_LIBRARY:WHOLE_ARCHIVE,ssbm_runtime>")
        pf_configure_ssbm_decomp_target(ssbm_match_root_link_test FALSE)
        add_test(
            NAME ssbm.match_root_link
            COMMAND ssbm_match_root_link_test)
        set_tests_properties(
            ssbm.match_root_link
            PROPERTIES
                PASS_REGULAR_EXPRESSION "ssbm-match-root-link=pass")

        add_executable(
            ssbm_match_root_frontier_test
            tests/ssbm/test_native_match_root_frontier.cpp
            src/ssbm/asset_pack.cpp
            src/ssbm/effect_particles.cpp
            src/ssbm/joint_trees.cpp
            src/ssbm/mapped_pack.cpp
            src/ssbm/native_effect_banks.cpp
            src/ssbm/native_compat/native_effect_bank_api.h
            src/ssbm/native_item_common.cpp
            src/ssbm/native_compat/native_archive_root_api.h
            src/ssbm/native_compat/native_fighter_common_api.h
            src/ssbm/native_compat/native_item_common_api.h
            src/ssbm/native_player_common.cpp
            src/ssbm/native_compat/native_player_common_api.h
            src/ssbm/native_stage_assets.cpp
            src/ssbm/native_compat/native_stage_assets_api.h
            src/ssbm/player_common.cpp
            src/ssbm/source_catalog.cpp
            src/ssbm/source_graphs.cpp
            src/ssbm/stage_collision.cpp
            src/ssbm/stage_ground_params.cpp
            src/ssbm/stage_joint_animations.cpp
            src/ssbm/stage_map_heads.cpp)
        target_include_directories(
            ssbm_match_root_frontier_test
            PRIVATE src/ssbm)
        target_link_libraries(
            ssbm_match_root_frontier_test
            PRIVATE
                ssbm_rooted_match_import)
        if(UNIX AND NOT APPLE)
            target_compile_definitions(
                ssbm_match_root_frontier_test PRIVATE _FILE_OFFSET_BITS=64)
        endif()
        target_compile_features(
            ssbm_match_root_frontier_test PRIVATE cxx_std_20)
        set_target_properties(
            ssbm_match_root_frontier_test
            PROPERTIES
                CXX_EXTENSIONS OFF)
        pf_enable_cpp_project_warnings(ssbm_match_root_frontier_test)
        pf_apply_build_mode(ssbm_match_root_frontier_test)
        add_test(
            NAME ssbm.match_root_frontier
            COMMAND ssbm_match_root_frontier_test)
        set_tests_properties(
            ssbm.match_root_frontier
            PROPERTIES
                PASS_REGULAR_EXPRESSION "ssbm-match-root-frontier=(pass|complete)")

        add_executable(
            ssbm_runtime_frontier_test
            tests/ssbm/test_native_runtime_frontier.cpp)
        target_link_libraries(
            ssbm_runtime_frontier_test PRIVATE ssbm_pack_file)
        target_compile_features(
            ssbm_runtime_frontier_test PRIVATE cxx_std_20)
        set_target_properties(
            ssbm_runtime_frontier_test
            PROPERTIES
                CXX_EXTENSIONS OFF)
        pf_enable_cpp_project_warnings(ssbm_runtime_frontier_test)
        pf_apply_build_mode(ssbm_runtime_frontier_test)

        add_executable(
            ssbm_native_match_setup_test
            tests/ssbm/test_native_match_setup.c)
        target_link_libraries(
            ssbm_native_match_setup_test
            PRIVATE "$<LINK_LIBRARY:WHOLE_ARCHIVE,ssbm_runtime>")
        pf_configure_ssbm_decomp_target(ssbm_native_match_setup_test FALSE)
        add_test(
            NAME ssbm.native_match_setup
            COMMAND ssbm_native_match_setup_test)
        set_tests_properties(
            ssbm.native_match_setup
            PROPERTIES
                PASS_REGULAR_EXPRESSION "ssbm-native-match-setup=pass")

        add_executable(ssbm_native_screen_ko_test
            tests/ssbm/test_native_screen_ko.c)
        target_link_libraries(ssbm_native_screen_ko_test
            PRIVATE "$<LINK_LIBRARY:WHOLE_ARCHIVE,ssbm_runtime>")
        pf_configure_ssbm_decomp_target(ssbm_native_screen_ko_test FALSE)
        add_test(NAME ssbm.native_screen_ko COMMAND ssbm_native_screen_ko_test)
        set_tests_properties(ssbm.native_screen_ko PROPERTIES
            PASS_REGULAR_EXPRESSION "ssbm-native-screen-ko=pass")

        add_executable(ssbm_native_wobble_test tests/ssbm/test_native_wobble.c)
        pf_configure_ssbm_decomp_target(ssbm_native_wobble_test FALSE)
        add_test(NAME ssbm.native_wobble COMMAND ssbm_native_wobble_test)
        set_tests_properties(ssbm.native_wobble PROPERTIES
            PASS_REGULAR_EXPRESSION "ssbm-native-wobble=pass")

        add_executable(
            ssbm_native_player_mapping_test
            tests/ssbm/test_native_player_mapping.c
            "${PF_SSBM_NATIVE_IMPORT_DIR}/adapted-source/src/melee/pl/player.c")
        pf_configure_ssbm_decomp_target(
            ssbm_native_player_mapping_test FALSE)
        if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
            target_compile_options(
                ssbm_native_player_mapping_test
                PRIVATE -ffunction-sections -fdata-sections)
            target_link_options(
                ssbm_native_player_mapping_test PRIVATE -Wl,--gc-sections)
        endif()
        add_test(
            NAME ssbm.native_player_mapping
            COMMAND ssbm_native_player_mapping_test)
        set_tests_properties(
            ssbm.native_player_mapping
            PROPERTIES
                PASS_REGULAR_EXPRESSION "ssbm-native-player-mapping=pass")

        add_executable(
            ssbm_native_fighter_state_test
            tests/ssbm/test_native_fighter_state.c
            src/ssbm/native_compat/native_fighter_state.c)
        pf_configure_ssbm_decomp_target(
            ssbm_native_fighter_state_test FALSE)
        add_test(
            NAME ssbm.native_fighter_state
            COMMAND ssbm_native_fighter_state_test)
        set_tests_properties(
            ssbm.native_fighter_state
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "ssbm-native-fighter-state=pass awake=2 sleeping-suppressed=2")

        add_executable(
            ssbm_gobj_scheduler_test
            tests/ssbm/test_gobj_scheduler.c)
        target_link_libraries(ssbm_gobj_scheduler_test PRIVATE ssbm_decomp_import)
        pf_configure_ssbm_decomp_target(ssbm_gobj_scheduler_test FALSE)
        if(MSVC)
            target_link_options(ssbm_gobj_scheduler_test PRIVATE /OPT:REF)
        elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
            target_link_options(ssbm_gobj_scheduler_test PRIVATE -Wl,--gc-sections)
        endif()
        add_test(NAME ssbm.gobj_scheduler COMMAND ssbm_gobj_scheduler_test)
        set_tests_properties(
            ssbm.gobj_scheduler
            PROPERTIES
                PASS_REGULAR_EXPRESSION "gobj-scheduler=pass")

        add_executable(
            ssbm_ft_damage_layout_test
            tests/ssbm/test_native_ft_damage_layout.c)
        pf_configure_ssbm_decomp_target(ssbm_ft_damage_layout_test FALSE)
        add_test(
            NAME ssbm.ft_damage_layout
            COMMAND ssbm_ft_damage_layout_test)
        set_tests_properties(
            ssbm.ft_damage_layout
            PROPERTIES
                PASS_REGULAR_EXPRESSION "native-ft-damage-layout=pass")

        add_executable(ssbm_native_motion_word_layout_test
            tests/ssbm/test_native_motion_word_layout.c)
        pf_configure_ssbm_decomp_target(ssbm_native_motion_word_layout_test FALSE)
        add_test(NAME ssbm.native_motion_word_layout
            COMMAND ssbm_native_motion_word_layout_test)

        add_executable(
            ssbm_native_fighter_anim_flags_layout_test
            tests/ssbm/test_native_fighter_anim_flags_layout.c)
        pf_configure_ssbm_decomp_target(
            ssbm_native_fighter_anim_flags_layout_test FALSE)
        add_test(
            NAME ssbm.native_fighter_anim_flags_layout
            COMMAND ssbm_native_fighter_anim_flags_layout_test)
        set_tests_properties(
            ssbm.native_fighter_anim_flags_layout
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-fighter-anim-flags-layout=pass accessors=13 x7-raw=00000140")

        add_executable(
            ssbm_native_item_attr_layout_test
            tests/ssbm/test_native_item_attr_layout.c)
        pf_configure_ssbm_decomp_target(
            ssbm_native_item_attr_layout_test FALSE)
        add_test(
            NAME ssbm.native_item_attr_layout
            COMMAND ssbm_native_item_attr_layout_test)
        set_tests_properties(
            ssbm.native_item_attr_layout
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-item-attr-layout=pass raw=01,28,00,00")

        add_executable(
            ssbm_native_command_layout_test
            tests/ssbm/test_native_command_layout.c)
        pf_configure_ssbm_decomp_target(ssbm_native_command_layout_test FALSE)
        add_test(
            NAME ssbm.native_command_layout
            COMMAND ssbm_native_command_layout_test)
        set_tests_properties(
            ssbm.native_command_layout
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-command-layout=pass words=4 motion=1 pointer=1")

        add_executable(
            ssbm_native_command_loop_test
            tests/ssbm/test_native_command_loop.c)
        target_link_libraries(
            ssbm_native_command_loop_test PRIVATE ssbm_decomp_adapted_providers)
        pf_configure_ssbm_decomp_target(ssbm_native_command_loop_test FALSE)
        if(MSVC)
            target_link_options(
                ssbm_native_command_loop_test PRIVATE /OPT:REF)
        elseif(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
            target_link_options(
                ssbm_native_command_loop_test PRIVATE -Wl,--gc-sections)
        endif()
        add_test(
            NAME ssbm.native_command_loop
            COMMAND ssbm_native_command_loop_test)
        set_tests_properties(
            ssbm.native_command_loop
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-command-loop=pass iterations=3 return-targets=2")

        add_executable(
            ssbm_native_pad_input_test
            tests/ssbm/test_native_pad_input.c)
        target_link_libraries(
            ssbm_native_pad_input_test PRIVATE ssbm_decomp_import)
        pf_configure_ssbm_decomp_target(ssbm_native_pad_input_test FALSE)
        add_test(
            NAME ssbm.native_pad_input
            COMMAND ssbm_native_pad_input_test)
        set_tests_properties(
            ssbm.native_pad_input
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-pad-input=pass players=4 edges=2 raw-axes=4 ucf-history=1 ucf-cardinals=2 ucf-shield-drop=2 rng=1")

        add_executable(
            ssbm_native_lbvector_test
            tests/ssbm/test_native_lbvector.c)
        target_link_libraries(
            ssbm_native_lbvector_test PRIVATE ssbm_rooted_match_import)
        pf_configure_ssbm_decomp_target(ssbm_native_lbvector_test FALSE)
        if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
            target_link_options(
                ssbm_native_lbvector_test PRIVATE -Wl,--gc-sections)
        endif()
        add_test(
            NAME ssbm.native_lbvector
            COMMAND ssbm_native_lbvector_test)
        set_tests_properties(
            ssbm.native_lbvector
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-lbvector=pass mirror-fmadds=3 witness=wall-reflect")

        add_executable(ssbm_native_slippi_spawn_test
            tests/ssbm/test_native_slippi_spawn.c
            src/ssbm/native_compat/native_slippi_spawn.c)
        pf_configure_ssbm_decomp_target(ssbm_native_slippi_spawn_test FALSE)
        add_test(NAME ssbm.native_slippi_spawn COMMAND ssbm_native_slippi_spawn_test)

        add_executable(ssbm_native_fd_scene_test
            tests/ssbm/test_native_fd_scene.c
            src/ssbm/native_compat/native_fd_scene.c)
        target_include_directories(ssbm_native_fd_scene_test PRIVATE src/ssbm/native_compat)
        add_test(NAME ssbm.native_fd_scene COMMAND ssbm_native_fd_scene_test)
        set_tests_properties(ssbm.native_fd_scene PROPERTIES
            PASS_REGULAR_EXPRESSION "ssbm-fd-scene=pass")

        add_executable(
            ssbm_native_slippi_test
            tests/ssbm/test_native_slippi.c
            src/ssbm/native_compat/native_slippi.c)
        pf_configure_ssbm_decomp_target(ssbm_native_slippi_test FALSE)
        add_test(
            NAME ssbm.native_slippi
            COMMAND ssbm_native_slippi_test)
        set_tests_properties(
            ssbm.native_slippi
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-slippi=pass offline=1 neutral-spawns=4 online-bounds=4 exclusions=3 stadium-preload=2 frozen=1 stadium-monitor=5")

        add_executable(
            ssbm_native_quantize_test
            tests/ssbm/test_native_quantize.c)
        pf_configure_ssbm_decomp_target(ssbm_native_quantize_test FALSE)
        add_test(
            NAME ssbm.native_quantize
            COMMAND ssbm_native_quantize_test)
        set_tests_properties(
            ssbm.native_quantize
            PROPERTIES
                PASS_REGULAR_EXPRESSION "native-quantize=pass")

        add_executable(
            ssbm_native_msl_math_test
            tests/ssbm/test_native_msl_math.c
            src/ssbm/native_compat/native_arithmetic.c)
        if(UNIX)
            target_link_libraries(ssbm_native_msl_math_test PRIVATE m)
        endif()
        pf_configure_ssbm_decomp_target(ssbm_native_msl_math_test FALSE)
        add_test(
            NAME ssbm.native_msl_math
            COMMAND ssbm_native_msl_math_test)
        set_tests_properties(
            ssbm.native_msl_math
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-msl-math=pass fma_vectors=7 fmodf_vectors=6 conversion_vectors=5 sqrt_vectors=8")

        add_executable(
            ssbm_native_texture_tables_test
            tests/ssbm/test_native_texture_tables.c
            src/ssbm/native_compat/native_texture_tables.c)
        pf_configure_ssbm_decomp_target(ssbm_native_texture_tables_test FALSE)
        add_test(NAME ssbm.native_texture_tables COMMAND ssbm_native_texture_tables_test)

        add_executable(
            ssbm_native_gx_texture_test
            tests/ssbm/test_native_gx_texture.c
            src/ssbm/native_compat/native_gx_texture.c)
        target_include_directories(
            ssbm_native_gx_texture_test
            PRIVATE "${PF_SSBM_DECOMP_SOURCE_DIR}/extern/dolphin/include")
        target_compile_features(ssbm_native_gx_texture_test PRIVATE c_std_17)
        add_test(
            NAME ssbm.native_gx_texture
            COMMAND ssbm_native_gx_texture_test)
        set_tests_properties(
            ssbm.native_gx_texture
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-gx-texture=pass vectors=5 fountain_bytes=9600")

        add_executable(
            ssbm_native_os_interrupts_test
            tests/ssbm/test_native_os_interrupts.c
            src/ssbm/native_compat/native_fail_closed_boundaries.c)
        add_test(
            NAME ssbm.native_os_interrupts
            COMMAND ssbm_native_os_interrupts_test)
        set_tests_properties(
            ssbm.native_os_interrupts
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-os-interrupts=pass nested=1 restore=1")

        add_executable(
            ssbm_native_ps_math_test
            tests/ssbm/test_native_ps_math.c)
        pf_configure_ssbm_decomp_target(ssbm_native_ps_math_test FALSE)
        add_test(
            NAME ssbm.native_ps_math
            COMMAND ssbm_native_ps_math_test)
        set_tests_properties(
            ssbm.native_ps_math
            PROPERTIES
                PASS_REGULAR_EXPRESSION
                    "native-ps-math=pass fres_vectors=9 frsqrte_vectors=57")

        add_test(
            NAME ssbm.native_root_materializer
            COMMAND
                "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/tools/test_materialize_native_root_closure.py")
        set_tests_properties(
            ssbm.native_root_materializer
            PROPERTIES
                PASS_REGULAR_EXPRESSION "Ran 4 tests")
    endif()
endif()

# Test assertions must execute in the optimized build as well.
get_property(ssbmsim_targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)
foreach(target IN LISTS ssbmsim_targets)
    if(target MATCHES "_test$")
        target_compile_options(${target} PRIVATE -UNDEBUG)
    endif()
endforeach()
