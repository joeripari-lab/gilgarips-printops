# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project_dir = Path(SPECPATH)
icon_file = project_dir / "assets" / "icon.ico"

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + collect_submodules("webview")
    + [
        "multipart",
        "python_multipart",
        "google.genai",
        "backend.main",
        "backend.file_manager",
        "backend.packaging",
        "backend.slicer_engine",
        "backend.gemini_service",
        "backend.etsy_service",
        "backend.updater_service",
    ]
)

a = Analysis(
    ["run.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[
        (str(project_dir / "frontend"), "frontend"),
        (str(project_dir / "assets"), "assets"),
    ],
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="GilgaripsPrintOps",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file) if icon_file.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GilgaripsPrintOps",
)

