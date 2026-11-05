# PyInstaller recipe for DeskMate.exe            run:  pyinstaller packaging/deskmate.spec
#
# "onedir" build: dist/DeskMate/DeskMate.exe plus an _internal folder. It starts much faster than a
# single-file exe (nothing to unpack on every launch) and antivirus tools trust it more.
# The characters/ folder is bundled; the image tools (numpy, rembg, ...) are NOT, they're dev-only.

import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "deskmate" / "__init__.py").read_text()).group(1)

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    # holidays: each country is its own module (found by name at run time), plus the English names.
    datas=[(str(ROOT / "characters"), "characters")] + collect_data_files("holidays"),
    hiddenimports=["deskmate.chatbox", "deskmate.chat"] + collect_submodules("holidays"),  # (lazy imports)
    excludes=["tkinter", "numpy", "PIL", "cv2", "rembg", "onnxruntime", "unittest", "pydoc"],
    noarchive=False,
)


def _wanted(entry) -> bool:
    """Leave out big Qt parts DeskMate never uses (English-only menus, plain 2D drawing)."""
    parts = entry[0].replace("\\", "/").lower().split("/")
    name = parts[-1]
    return not ("translations" in parts or name.startswith(("opengl32sw", "qt6pdf", "qt6quick", "qt6qml"))
                or name.startswith(("libqt6pdf", "libqt6quick", "libqt6qml")))


a.datas = [d for d in a.datas if _wanted(d)]
a.binaries = [b for b in a.binaries if _wanted(b)]
pyz = PYZ(a.pure)

version_file = None
if sys.platform == "win32":  # the "Details" tab in the .exe's Properties
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )

    numbers = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3]) + (0,)
    version_file = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "MuizKmz"),
                StringStruct("FileDescription", "DeskMate - a desktop companion"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "DeskMate"),
                StringStruct("OriginalFilename", "DeskMate.exe"),
                StringStruct("ProductName", "DeskMate"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DeskMate",
    icon=str(ROOT / "packaging" / "deskmate.ico"),
    version=version_file,
    console=False,  # no black console window
    upx=False,      # UPX-packed exes upset antivirus software
)
coll = COLLECT(exe, a.binaries, a.datas, name="DeskMate", upx=False)
