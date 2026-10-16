"""Launch the self-contained desktop demo."""

import argparse
import sys
from importlib.resources import files

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from pi_dvs.engine import DemoEngine
from pi_dvs.library import demo_library
from pi_dvs.presentation import Controller


def create_window() -> tuple[QQmlApplicationEngine, Controller]:
    controller = Controller(demo_library(), DemoEngine())
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"controller": controller})
    engine.load(QUrl.fromLocalFile(str(files("pi_dvs").joinpath("ui", "Main.qml"))))
    return engine, controller


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the silent pi-dvs desktop demo.")
    parser.add_argument(
        "--demo", action="store_true", help="Use bundled sample tracks (the default)"
    )
    parser.parse_args()
    app = QGuiApplication([sys.argv[0]])
    app.setApplicationName("pi-dvs")
    app.setOrganizationName("pi-dvs")
    QQuickStyle.setStyle("Basic")
    engine, controller = create_window()
    if not engine.rootObjects():
        print("Could not load the pi-dvs interface.", file=sys.stderr)
        return 1
    # Keep the controller and engine alive until the event loop exits.
    result = app.exec()
    engine.deleteLater()
    controller.deleteLater()
    return result
