cmake_minimum_required(VERSION 3.16)

# the Debian package of the dispatcher; nothing is compiled
project(hsm-dispatcher-py VERSION 0.1.0 LANGUAGES NONE)

# the place of the pure Python modules on Debian
set(PYTHON_INSTALL_DIR "lib/python3/dist-packages" CACHE STRING
    "the directory of the hsmd modules under the prefix")
set(DOC_INSTALL_DIR "share/doc/python3-hsm-dispatcher")
# the package directories do not follow the umask of the build
set(CMAKE_INSTALL_DEFAULT_DIRECTORY_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE
    GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE)

install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/hsmd.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd_model.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd_build.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd_reader.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd_actions.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd_step.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd_components.py
        DESTINATION ${PYTHON_INSTALL_DIR})

install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/ChangeLog.md
              ${CMAKE_CURRENT_SOURCE_DIR}/README.md
              ${CMAKE_CURRENT_SOURCE_DIR}/LICENSE
              ${CMAKE_CURRENT_SOURCE_DIR}/docs/ARCHITECTURE.md
              ${CMAKE_CURRENT_SOURCE_DIR}/docs/API.md
              ${CMAKE_CURRENT_SOURCE_DIR}/docs/API-ru.md
        DESTINATION ${DOC_INSTALL_DIR})

# the tests need the CyberiadaML binding in this Python
# (-DPython3_EXECUTABLE=... selects another one)
find_package(Python3 3.8 COMPONENTS Interpreter)
if(Python3_FOUND)
  enable_testing()
  add_test(NAME scenarios
           COMMAND ${Python3_EXECUTABLE} -B run.py
           WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/test)
endif()

configure_file("${PROJECT_SOURCE_DIR}/HsmDispatcherPackOptions.cmake.in"
               "${PROJECT_BINARY_DIR}/HsmDispatcherPackOptions.cmake"
               @ONLY)
set(CPACK_PROJECT_CONFIG_FILE "${PROJECT_BINARY_DIR}/HsmDispatcherPackOptions.cmake")

include(CPack)
