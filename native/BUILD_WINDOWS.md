# Windows Native Build

This is the Windows build path for the working native MuPDF backend.

## What is true right now

- The repo already has:
  - a C ABI contract in `mupdf_bridge.h`
  - a MuPDF-backed DLL implementation in `mupdf_bridge_stub.cpp`
  - a Python `ctypes` bridge in `services/native_pdf_backend.py`
  - PyInstaller discovery for `anki_pdf_native.dll`
- The native build expects:
  - Visual Studio 2022 Build Tools with Desktop C++
  - MSBuild
  - CMake
  - MuPDF source checked out under `native/mupdf-src`

## Install prerequisites

### 1. Visual Studio C++ Build Tools

Install Microsoft Visual Studio Build Tools / Visual Studio with the
`Desktop development with C++` workload.

Official references:
- Microsoft install guide:
  [Install C and C++ support in Visual Studio](https://learn.microsoft.com/en-us/cpp/build/vscpp-step-0-installation?view=msvc-160)
- Workload ID reference:
  [Microsoft.VisualStudio.Workload.VCTools](https://learn.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-build-tools?view=vs-2022)

Minimum components to keep checked:
- Desktop development with C++
- MSVC toolset
- Windows SDK
- CMake tools for Windows

### 2. MuPDF source

Get the MuPDF source tree.

Official references:
- [MuPDF Install Guide](https://mupdf.readthedocs.io/en/1.27.0/guide/install.html)
- [MuPDF Quick Start Guide](https://mupdf.readthedocs.io/en/1.22.0/quick-start-guide.html)
- [MuPDF Core Overview](https://mupdf.com/core)

The official docs say that on Windows you build using
`platform/win32/mupdf.sln`, and this repo’s helper script follows that path.

### 3. CMake

Visual Studio Build Tools usually installs a bundled CMake. The helper script
will use that copy if `cmake` is not already on PATH.

## After install, verify tools

Open a fresh `x64 Native Tools Command Prompt for VS 2022` or a new PowerShell
window after install and run:

```powershell
cl
cmake --version
```

Expected:
- `cl` should print the MSVC compiler banner
- `cmake --version` should print a version

## Build the native DLL

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\native\build_windows.ps1
```

That should produce:

```text
native\build\Release\anki_pdf_native.dll
```

## What this gives you

This build:
- builds MuPDF static libraries first if needed
- configures the native bridge with CMake
- links `anki_pdf_native.dll` against MuPDF
- leaves the DLL at `native\build\Release\anki_pdf_native.dll`

## Next code step after tools are installed

The next improvement area is no longer “make it render at all.” It is:

1. native tile / viewport rendering
2. native full initial load for the PDF annotation window
3. native annotation enumeration / save helpers
4. changed-page-only refresh from the native layer too

## Practical recommendation

Do this in order:

1. Install Visual Studio C++ tools
2. Clone MuPDF into `native/mupdf-src`
3. Run `native/build_windows.ps1`
4. Confirm the app reports `native MuPDF DLL`
5. Then keep iterating on native rendering features
