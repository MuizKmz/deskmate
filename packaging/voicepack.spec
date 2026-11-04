# PyInstaller recipe for the voice pack           run:  pyinstaller packaging/voicepack.spec
#
# Builds dist/DeskMate-Voice/DeskMate-Voice.exe: a small offline voice server (Kokoro, through
# kokoro-onnx + espeak-ng) that DeskMate downloads once and starts by itself. It's a separate
# program on purpose: DeskMate.exe never contains the voice engine. The voice model files
# (models/) are added next to it by .github/workflows/voicepack.yml, not by this spec.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent

datas, binaries, hiddenimports = [], [], []
for package in ("kokoro_onnx", "espeakng_loader", "phonemizer"):  # config.json, espeak-ng + its data
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata("kokoro_onnx")

a = Analysis(
    [str(ROOT / "packaging" / "voice_launch.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PySide6", "PIL", "cv2", "matplotlib", "pandas", "scipy", "deskmate"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DeskMate-Voice",
    icon=str(ROOT / "packaging" / "deskmate.ico"),
    console=False,  # DeskMate starts it hidden; it logs to voicepack.log
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="DeskMate-Voice", upx=False)
