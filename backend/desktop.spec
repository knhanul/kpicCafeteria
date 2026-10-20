import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)


root = Path(SPECPATH)
datas = [
    (str(root / "app" / "static"), "app/static"),
    (str(root / "app" / "templates"), "app/templates"),
    (str(root.parent / "docs" / "template"), "docs/template"),
]
hiddenimports = collect_submodules("webview")

version_text = os.environ.get("KPI_BUILD_VERSION", "").strip() or "1.0.0"
build_date = os.environ.get("KPI_BUILD_DATE", "").strip()
numbers = [int(value) for value in re.findall(r"\d+", version_text)]
filevers = tuple((numbers + [0] * 4)[:4]) if numbers else (1, 0, 0, 0)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=filevers,
        prodvers=filevers,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "041204B0",
                    [
                        StringStruct("CompanyName", "KPIC"),
                        StringStruct("FileDescription", "구내식당 관리 PC 버전"),
                        StringStruct("FileVersion", version_text),
                        StringStruct("InternalName", "KPICCafeteria"),
                        StringStruct("ProductName", "구내식당 관리"),
                        StringStruct("ProductVersion", version_text),
                        StringStruct("BuildDate", build_date),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x412, 0x04B0])]),
    ],
)

icon_path = root.parent / "desktop-build" / "KPICCafeteria.ico"

a = Analysis(
    [str(root / "desktop_launcher.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["playwright", "psycopg", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KPICCafeteria",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_path) if icon_path.exists() else None,
    version=version_info,
)
