# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出 FolderOps.app（含内置 7zz，解压开箱可用）。

用法（项目根目录）：.venv-build/bin/pyinstaller --noconfirm packaging/FolderOps.spec
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = Path(SPECPATH).parent
ICON = str(PROJECT_ROOT / "packaging" / "FolderOps.icns")
SEVEN_ZIP = PROJECT_ROOT / "vendor" / "macos-arm64" / "7zz"

sys.path.insert(0, str(PROJECT_ROOT))
from folder_ops import __version__ as APP_VERSION  # noqa: E402

datas = collect_data_files("tkinterdnd2")
hiddenimports = collect_submodules("tkinterdnd2")

binaries = []
if SEVEN_ZIP.is_file():
    # 打包后位于 Contents/Frameworks/vendor/macos-arm64/7zz，由 seven_zip.discover 自动发现
    binaries.append((str(SEVEN_ZIP), "vendor/macos-arm64"))

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FolderOps",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FolderOps",
)

app = BUNDLE(
    coll,
    name="FolderOps.app",
    icon=ICON,
    bundle_identifier="io.folderops.app",
    info_plist={
        "CFBundleName": "FolderOps",
        "CFBundleDisplayName": "folder-ops 文件夹规则引擎",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSHumanReadableCopyright": "© 2026 folder-ops contributors",
    },
)
