# Native PDF Backend

This folder now contains the first working native MuPDF backend for the app.

## Goal

Replace browser-style or full-document bitmap viewing with a native MuPDF-based
viewer/editor path that can:

- render only visible tiles/pages
- preserve sharp zoom at all scales
- track dirty pages from annotation edits
- return changed page numbers back to the Python app
- avoid whole-document rerender after annotation saves

## Why this shape

The current app is Python + PyQt5 + PyInstaller. The safest native integration
for that stack is:

1. a small Windows DLL written in C/C++
2. a plain C ABI exported from that DLL
3. a Python `ctypes` bridge in `services/native_pdf_backend.py`

This avoids hard-coupling the app to `pybind11`, `sip`, or a full Qt/C++
application rewrite on day one.

## Proposed architecture

### Native side

- `mupdf_bridge.h`
- `mupdf_bridge_stub.cpp`
- later:
  - `mupdf_document.cpp`
  - `mupdf_renderer.cpp`
  - `mupdf_annotations.cpp`
  - `mupdf_tiles.cpp`

### Python side

- `services/native_pdf_backend.py`
- later:
  - `services/native_pdf_renderer.py`
  - optional `ui/native_pdf_host.py`

## Phase plan

### Phase 1

Native DLL discovery + fallback only.

Done:
- locate `anki_pdf_native.dll`
- load it with `ctypes`
- query version/error
- keep Python renderer as fallback

### Phase 2

Native page rendering API.

Done:
- `ao_pdf_open_document`
- `ao_pdf_close_document`
- `ao_pdf_get_page_count`
- `ao_pdf_get_page_size`
- `ao_pdf_render_page_bgra`
- `ao_pdf_free_buffer`

Contract in `mupdf_bridge.h`:
- `ao_pdf_open_document`
- `ao_pdf_close_document`
- `ao_pdf_get_page_count`
- `ao_pdf_get_page_size`
- `ao_pdf_render_page_bgra`
- `ao_pdf_free_buffer`

### Phase 3

Tile rendering + viewport-aware rendering.

Add exports for:
- render clipped region / tile
- render at arbitrary zoom
- invalidate only changed pages

This is where the app starts to feel closer to Sumatra.

### Phase 4

Native annotation edit pipeline.

Add exports for:
- enumerate annotations
- add ink / highlight
- delete annotation
- save incrementally
- return dirty page list

## Build notes

This repo now has:
- a working CMake project in `native/CMakeLists.txt`
- a helper build script in `native/build_windows.ps1`
- a checked-in MuPDF source tree under `native/mupdf-src`
- a Python `ctypes` bridge that reports native backend status

The full Windows setup steps live in:
- `native/BUILD_WINDOWS.md`

The practical Windows build path is:

1. install Visual Studio Build Tools with C++
2. build MuPDF static libs from `native/mupdf-src/platform/win32/mupdf.sln`
3. run `native/build_windows.ps1`
4. use the output at `native/build/Release/anki_pdf_native.dll`

## Packaging notes

When the DLL exists, add it to `AnkiOcclusion.spec` as a binary so PyInstaller
ships it next to the executable.

## Recommendation

Start by moving the **PDF annotation window** to the native backend first.
That gives the biggest user-visible gain with the smallest blast radius.
