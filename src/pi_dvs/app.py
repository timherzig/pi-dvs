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
from pi_dvs.link.service import LinkService
from pi_dvs.presentation import Controller
from pi_dvs.xwax import XwaxEngine


def create_window(
    library_root: Path | None = None,
    format_choice: str = "auto",
    sockets: tuple[Path, Path] | None = None,
    link: LinkService | None = None,
) -> tuple[QQmlApplicationEngine, Controller]:
    library = (
        Library((), name="Open a Rekordbox USB", source_id="xwax", format_name="No library")
        if sockets
        else demo_library()
    )
    controller = Controller(library, XwaxEngine(sockets) if sockets else DemoEngine(), link=link)
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
    parser.add_argument(
        "--link-interface", help="Enable Pro DJ Link on this wired interface (e.g. en7 or eth0)"
    )
    parser.add_argument(
        "--link-helper", type=Path, help="Path to the separately built pi-dvs-link helper"
    )
    parser.add_argument("--link-cache", type=Path, help="Host-local Link cache directory")
    parser.add_argument(
        "--link-cache-mib",
        type=int,
        default=2048,
        help="Audio cache capacity in MiB (default: 2048)",
    )
    args = parser.parse_args()
    if bool(args.link_interface) != bool(args.link_helper):
        parser.error("Use --link-interface and --link-helper together")
    if args.link_cache_mib < 1:
        parser.error("--link-cache-mib must be positive")
    if args.demo and args.xwax_sockets:
        parser.error("--demo cannot be combined with --xwax-sockets")
    sockets = (args.xwax_sockets[0], args.xwax_sockets[1]) if args.xwax_sockets else None
    if sockets and sockets[0].absolute() == sockets[1].absolute():
        parser.error("Deck A and B need different engine sockets")
    app = QGuiApplication([sys.argv[0]])
    app.setApplicationName("pi-dvs")
    app.setOrganizationName("pi-dvs")
    QQuickStyle.setStyle("Basic")
    from PySide6.QtCore import QStandardPaths

    link = None
    if args.link_interface:
        cache = (
            args.link_cache
            or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
            / "link"
        )
        link = LinkService(
            args.link_interface,
            args.link_helper.expanduser().absolute(),
            cache.expanduser().absolute(),
            cache_bytes=args.link_cache_mib * 1024**2,
        )
    engine, controller = create_window(args.library, args.format, sockets, link)
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
