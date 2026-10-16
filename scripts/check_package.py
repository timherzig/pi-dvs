"""Install built artifacts outside the source tree and exercise packaged QML."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

SMOKE_TEST = """
from importlib.resources import files
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuickControls2 import QQuickStyle
from pi_dvs.app import create_window
from pi_dvs.library import demo_library

app = QGuiApplication([])
QQuickStyle.setStyle("Basic")
library = demo_library()
assert library.tracks, "Packaged library is empty"
assert any(track.artwork for track in library.tracks), "Packaged artwork is missing"
assert all(track.artwork.is_file() for track in library.tracks if track.artwork)
assert files("pi_dvs").joinpath("ui", "Main.qml").is_file()
engine, controller = create_window()
assert engine.rootObjects(), "Installed QML window failed to load"
assert controller.trackCount == len(library.tracks)
warnings = []
engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
QTimer.singleShot(250, app.quit)
assert app.exec() == 0
assert not warnings, warnings
for window in engine.rootObjects():
    window.close()
engine.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
controller.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
print("Installed wheel: library, artwork, QML and event loop passed")
"""


def main() -> None:
    dist = Path("dist").resolve()
    wheels = list(dist.glob("*.whl"))
    archives = list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(archives) != 1:
        raise SystemExit("Expected exactly one wheel and one source archive; run make package.")
    requirements = dist / "requirements.txt"
    with TemporaryDirectory(prefix="pi-dvs-package-") as directory:
        python = Path(directory) / "venv" / "bin" / "python"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(python.parent.parent)], check=True
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--require-hashes",
                "-r",
                str(requirements),
            ],
            check=True,
        )
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheels[0])],
            check=True,
        )
        environment = os.environ | {
            "QT_QPA_PLATFORM": "offscreen",
            "QT_QUICK_BACKEND": "software",
        }
        subprocess.run(
            [str(python), "-I", "-c", SMOKE_TEST],
            cwd=directory,
            env=environment,
            check=True,
            timeout=30,
        )
    artifacts = sorted([*wheels, *archives, requirements])
    (dist / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts
        )
    )


if __name__ == "__main__":
    main()
