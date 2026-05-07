# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path.cwd()
NATIVE_DLL_CANDIDATES = [
    ROOT / "anki_pdf_native.dll",
    ROOT / "native" / "bin" / "anki_pdf_native.dll",
    ROOT / "native" / "build" / "Release" / "anki_pdf_native.dll",
]

binaries = []
for candidate in NATIVE_DLL_CANDIDATES:
    if candidate.exists():
        binaries.append((str(candidate), "."))
        break


a = Analysis(
    ['anki_occlusion_v19.py'],
    pathex=[],
    binaries=binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AnkiOcclusion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
