"""Launch the self-contained desktop demo."""

import argparse
import sys
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from pi_dvs.engine import DemoEngine
from pi_dvs.library import demo_library
from pi_dvs.presentation import Controller


def create_window(
    library_root: Path | None = None, format_choice: str = "auto"
) -> tuple[QQmlApplicationEngine, Controller]:
    controller = Controller(demo_library(), DemoEngine())
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"controller": controller})
    engine.load(QUrl.fromLocalFile(str(files("pi_dvs").joinpath("ui", "Main.qml"))))
    if library_root is not None:
        QTimer.singleShot(0, lambda: controller.openExport(str(library_root), format_choice))
    return engine, controller


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the silent pi-dvs desktop demo.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--demo", action="store_true", help="Use bundled sample tracks (the default)"
    )
    source.add_argument("--library", type=Path, help="Mounted Rekordbox USB root to import")
    parser.add_argument("--format", choices=("auto", "pdb", "onelibrary"), default="auto")
    args = parser.parse_args()
    app = QGuiApplication([sys.argv[0]])
    app.setApplicationName("pi-dvs")
    app.setOrganizationName("pi-dvs")
    QQuickStyle.setStyle("Basic")
    engine, controller = create_window(args.library, args.format)
    app.aboutToQuit.connect(controller.close)
    if not engine.rootObjects():
        print("Could not load the pi-dvs interface.", file=sys.stderr)
        return 1
    # Keep the controller and engine alive until the event loop exits.
    result = app.exec()
    engine.deleteLater()
    controller.deleteLater()
    return result
