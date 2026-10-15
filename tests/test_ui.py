"""Exercise real QML controls and their Python bindings without audio hardware."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from pi_dvs.app import create_window


@pytest.fixture(scope="module")
def app():
    instance = QGuiApplication.instance() or QGuiApplication([])
    QQuickStyle.setStyle("Basic")
    yield instance


def _item(root, name):
    def visit(item):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            found = visit(child)
            if found is not None:
                return found
        return None

    result = visit(root.contentItem())
    assert result is not None, f"Missing UI control: {name}"
    return result


def _click(window, name):
    item = _item(window, name)
    assert item.isEnabled()
    point = item.mapToScene(QPoint(int(item.width() / 2), int(item.height() / 2))).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(20)


def test_search_load_transport_and_error_recovery_through_qml(app):
    engine, controller = create_window()
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    try:
        assert engine.rootObjects(), "QML window failed to load"
        window = engine.rootObjects()[0]
        QTest.qWait(100)
        _click(window, "loadA_after-hours")
        assert controller.decks[0]["status"] == "Loading"
        _click(window, "loadB_tidal")
        QTest.qWait(500)
        assert controller.decks[0]["title"] == "After Hours"
        assert controller.decks[1]["title"] == "Tidal Memory"
        assert controller.decks[0]["status"] == "Ready"
        _click(window, "playA")
        QTest.qWait(200)
        assert controller.decks[0]["playing"]
        assert controller.decks[0]["progress"] > 0
        assert not _item(window, "loadA_after-hours").isEnabled()
        assert controller.decks[1]["status"] == "Ready"
        _click(window, "playA")
        assert controller.decks[0]["status"] == "Paused"

        search = window.findChild(QObject, "searchField")
        search.setProperty("text", "cafe elan")
        QTest.qWait(50)
        assert controller.trackCount == 1
        _click(window, "loadA_cafe")
        QTest.qWait(450)
        assert controller.decks[0]["title"] == "Café Lumière"
        search.setProperty("text", "no results here")
        assert controller.trackCount == 0
        assert controller.decks[0]["title"] == "Café Lumière"

        search.setProperty("text", "archive")
        QTest.qWait(50)
        _click(window, "loadA_archive")
        QTest.qWait(450)
        assert controller.decks[0]["status"] == "Unavailable"
        assert controller.decks[0]["error"]
        _click(window, "unloadA")
        assert controller.decks[0]["status"] == "Empty"
        _click(window, "clearSearch")
        assert controller.trackCount == controller.totalTracks
        _click(window, "loadA_after-hours")
        QTest.qWait(450)
        assert controller.decks[0]["status"] == "Ready"
        assert not warnings
    finally:
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
        controller.deleteLater()
        QTest.qWait(20)
