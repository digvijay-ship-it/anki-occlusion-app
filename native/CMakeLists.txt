cmake_minimum_required(VERSION 3.20)

project(anki_pdf_native LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")

set(MUPDF_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/mupdf-src" CACHE PATH "Path to the MuPDF source tree")
set(MUPDF_BUILD_DIR "${MUPDF_ROOT}/platform/win32/x64/Release" CACHE PATH "Path to MuPDF's built x64 Release libraries")

if (NOT EXISTS "${MUPDF_ROOT}/include/mupdf/fitz/context.h")
    message(FATAL_ERROR "MuPDF headers not found under ${MUPDF_ROOT}. Build or clone MuPDF first.")
endif()

if (NOT EXISTS "${MUPDF_BUILD_DIR}/libmupdf.lib")
    message(FATAL_ERROR "MuPDF libraries not found under ${MUPDF_BUILD_DIR}. Build native/mupdf-src/platform/win32/mupdf.sln (target libmupdf) first.")
endif()

add_library(anki_pdf_native SHARED
    mupdf_bridge_stub.cpp
)

target_include_directories(anki_pdf_native
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${MUPDF_ROOT}/include
)

target_compile_definitions(anki_pdf_native
    PRIVATE
        WIN32_LEAN_AND_MEAN
        NOMINMAX
)

if (MSVC)
    target_compile_options(anki_pdf_native PRIVATE /utf-8 /EHsc)
endif()

target_link_directories(anki_pdf_native
    PRIVATE
        ${MUPDF_BUILD_DIR}
)

target_link_libraries(anki_pdf_native
    PRIVATE
        libmupdf
        libresources
        libthirdparty
        libpkcs7
        libleptonica
        libtesseract
        libextract
        libharfbuzz
        libzxing
        libmubarcode
        user32
        gdi32
        advapi32
        shell32
        ole32
        uuid
        comdlg32
        crypt32
        bcrypt
        Ws2_32
        normaliz
)

set_target_properties(anki_pdf_native PROPERTIES
    OUTPUT_NAME "anki_pdf_native"
)
