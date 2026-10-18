"""Compose the library UI with simulation or a local xwax connection."""

import argparse
import sys
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from pi_dvs.engine import DemoEngine
from pi_dvs.library import Library, demo_library
from pi_dvs.presentation import Controller
from pi_dvs.xwax import XwaxEngine


def create_window(
    library_root: Path | None = None,
    format_choice: str = "auto",
    sockets: tuple[Path, Path] | None = None,
) -> tuple[QQmlApplicationEngine, Controller]:
    library = (
        Library((), name="Open a Rekordbox USB", source_id="xwax", format_name="No library")
        if sockets
        else demo_library()
    )
    controller = Controller(library, XwaxEngine(sockets) if sockets else DemoEngine())
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"controller": controller})
    engine.load(QUrl.fromLocalFile(str(files("pi_dvs").joinpath("ui", "Main.qml"))))
    if library_root is not None:
        QTimer.singleShot(0, lambda: controller.openExport(str(library_root), format_choice))
    return engine, controller


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Browse music with simulated transport or a local xwax engine."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--demo", action="store_true", help="Use bundled sample tracks (the default)"
    )
    source.add_argument("--library", type=Path, help="Mounted Rekordbox USB root to import")
    parser.add_argument("--format", choices=("auto", "pdb", "onelibrary"), default="auto")
    parser.add_argument(
        "--xwax-sockets",
        nargs=2,
        type=Path,
        metavar=("DECK_A", "DECK_B"),
        help="Connect to two local patched xwax sockets instead of simulation",
    )
    args = parser.parse_args()
    if args.demo and args.xwax_sockets:
        parser.error("--demo cannot be combined with --xwax-sockets")
    sockets = (args.xwax_sockets[0], args.xwax_sockets[1]) if args.xwax_sockets else None
    if sockets and sockets[0].absolute() == sockets[1].absolute():
        parser.error("Deck A and B need different engine sockets")
    app = QGuiApplication([sys.argv[0]])
    app.setApplicationName("pi-dvs")
    app.setOrganizationName("pi-dvs")
    QQuickStyle.setStyle("Basic")
    engine, controller = create_window(args.library, args.format, sockets)
    app.aboutToQuit.connect(controller.close)
    if not engine.rootObjects():
        controller.close()
        print("Could not load the pi-dvs interface.", file=sys.stderr)
        return 1
    # Keep the controller and engine alive until the event loop exits.
    result = app.exec()
    engine.deleteLater()
    controller.deleteLater()
    return result
