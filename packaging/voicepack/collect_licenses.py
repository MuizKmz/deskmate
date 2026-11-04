"""Copy the license files of everything installed (what PyInstaller bundled) into a folder.

    python packaging/voicepack/collect_licenses.py dist/DeskMate-Voice/licenses
"""

from __future__ import annotations

import shutil
import sys
from importlib import metadata
from pathlib import Path

SKIP = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile",
        "pywin32-ctypes", "packaging"}
WORDS = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")


def main(target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    found = []
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name or name.lower() in SKIP:
            continue
        files = [f for f in dist.files or [] if any(w in f.name.upper() for w in WORDS)]
        folder = target / f"{name}-{dist.version}"
        for file in files:
            source = Path(dist.locate_file(file))
            if source.is_file():
                folder.mkdir(exist_ok=True)
                shutil.copy2(source, folder / source.name)
        summary = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        found.append(f"{name} {dist.version}: {summary.splitlines()[0] if summary else 'see its folder'}")
    (target / "PACKAGES.txt").write_text("\n".join(sorted(found, key=str.lower)) + "\n", encoding="utf-8")
    print("\n".join(sorted(found, key=str.lower)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
