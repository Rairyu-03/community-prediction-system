from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules


workspace = Path(SPECPATH).parent
hiddenimports = collect_submodules("uvicorn") + collect_submodules("sqlalchemy.dialects.sqlite")

a = Analysis(
    [str(workspace / "backend" / "standalone.py")],
    pathex=[str(workspace / "backend")],
    binaries=[],
    datas=[(str(workspace / "frontend" / "dist"), "frontend/dist")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "httpx"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CommunityPredictionSystem",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
