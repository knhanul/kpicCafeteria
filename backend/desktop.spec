from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


root = Path(SPECPATH)
datas = [
    (str(root / "app" / "static"), "app/static"),
    (str(root / "app" / "templates"), "app/templates"),
]
hiddenimports = collect_submodules("webview")

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
    [],
    exclude_binaries=True,
    name="KPICCafeteria",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="KPICCafeteria",
)
