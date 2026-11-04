cmake_minimum_required(VERSION 3.16)

# the Debian package of the dispatcher; nothing is compiled
project(hsm-dispatcher-py VERSION 0.1.0 LANGUAGES NONE)

# the place of the pure Python packages on Debian
set(PYTHON_INSTALL_DIR "lib/python3/dist-packages" CACHE STRING
    "the directory of the hsmd package under the prefix")
set(DOC_INSTALL_DIR "share/doc/python3-hsm-dispatcher")
# the package directories do not follow the umask of the build
set(CMAKE_INSTALL_DEFAULT_DIRECTORY_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE
    GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE)

install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/hsmd/__init__.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd/model.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd/build.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd/reader.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd/actions.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd/step.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd/components.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd/stream.py
              ${CMAKE_CURRENT_SOURCE_DIR}/hsmd/session.py
        DESTINATION ${PYTHON_INSTALL_DIR}/hsmd)

install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/ChangeLog.md
              ${CMAKE_CURRENT_SOURCE_DIR}/README.md
              ${CMAKE_CURRENT_SOURCE_DIR}/LICENSE
              ${CMAKE_CURRENT_SOURCE_DIR}/docs/ARCHITECTURE.md
              ${CMAKE_CURRENT_SOURCE_DIR}/docs/API.md
              ${CMAKE_CURRENT_SOURCE_DIR}/docs/API-ru.md
        DESTINATION ${DOC_INSTALL_DIR})

# the machine-readable (DEP-5) copyright, where the Debian policy wants it
install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/debian-copyright
        DESTINATION ${DOC_INSTALL_DIR} RENAME copyright)

# the tests need the CyberiadaML binding in this Python
# (-DPython3_EXECUTABLE=... selects another one)
find_package(Python3 3.8 COMPONENTS Interpreter)
if(Python3_FOUND)
  enable_testing()
  add_test(NAME scenarios
           COMMAND ${Python3_EXECUTABLE} -B run.py
           WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/test)
  add_test(NAME stream
           COMMAND ${Python3_EXECUTABLE} -B stream_test.py
           WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/test)
  add_test(NAME session
           COMMAND ${Python3_EXECUTABLE} -B session_test.py
           WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/test)
endif()

# optional per-release suffix (e.g. ubuntu2404) for the package version: the
# package is tested against that release's libraries and Python
set(DISTRO_TAG "" CACHE STRING "distribution suffix appended to the package version")
configure_file("${PROJECT_SOURCE_DIR}/HsmDispatcherPackOptions.cmake.in"
               "${PROJECT_BINARY_DIR}/HsmDispatcherPackOptions.cmake"
               @ONLY)
set(CPACK_PROJECT_CONFIG_FILE "${PROJECT_BINARY_DIR}/HsmDispatcherPackOptions.cmake")

include(CPack)
