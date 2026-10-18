"""Exercise real QML controls and their Python bindings without audio hardware."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject, QObject, QPoint, Qt
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
    if name.startswith(("loadA_", "loadB_")):
        # Find and scroll to the track instead of assuming the demo's insertion
        # order places every requested button inside the current viewport.
        track_list = window.findChild(QObject, "trackList")
        model = window.property("controller").libraryModel
        id_role = next(role for role, label in model.roleNames().items() if label == b"trackId")
        row = next(
            row
            for row in range(model.rowCount())
            if model.data(model.index(row), id_role) == name.split("_", 1)[1]
        )
        QMetaObject.invokeMethod(
            track_list,
            "positionViewAtIndex",
            Q_ARG(int, row),
            Q_ARG(int, 2),  # ListView.Contain
        )
        QTest.qWait(20)
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
        _click(window, "platterA")
        assert not controller.decks[0]["playing"]
        _click(window, "needleA")
        QTest.qWait(200)
        assert controller.decks[0]["playing"]
        assert controller.decks[0]["progress"] > 0
        assert not _item(window, "loadA_after-hours").isEnabled()
        assert controller.decks[1]["status"] == "Ready"
        assert not _item(window, "unloadA").isEnabled()
        # The engine also enforces protection for calls outside disabled QML controls.
        controller.loadTrack(0, "tidal")
        assert "Stop the record" in controller.notice
        controller.unload(0)
        assert "Stop the record" in controller.notice
        assert controller.decks[0]["title"] == "After Hours"
        _click(window, "platterA")
        assert controller.decks[0]["status"] == "Stopped"
        assert controller.decks[0]["needleDown"]
        assert not controller.notice
        assert _item(window, "loadA_after-hours").isEnabled()
        assert _item(window, "unloadA").isEnabled()

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
        assert controller.decks[0]["status"] == "Stopped"
        _click(window, "needleA")
        _click(window, "platterA")
        assert controller.decks[0]["status"] == "Ready"
        assert _item(window, "unloadA").isEnabled()
        controller.loadTrack(0, "unknown-track")
        assert controller.notice
        assert not warnings
    finally:
        controller.close()
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
        controller.deleteLater()
        QTest.qWait(20)


@pytest.mark.parametrize("deck", [0, 1])
@pytest.mark.parametrize("end_offset", [0.0, 0.01])
@pytest.mark.parametrize("control", ["needle", "platter"])
def test_stopping_vinyl_at_track_end_does_not_restart(app, monkeypatch, deck, end_offset, control):
    now = 0.0
    monkeypatch.setattr("pi_dvs.presentation.monotonic", lambda: now)
    engine, controller = create_window()
    # The clock moves explicitly between displaying transport state and handling the input.
    controller._timer.stop()
    target = "AB"[deck]
    other = "BA"[deck]
    try:
        window = engine.rootObjects()[0]
        QTest.qWait(100)
        _click(window, "load" + target + "_after-hours")
        _click(window, "load" + other + "_tidal")
        now = 1.0
        controller._tick()
        for name in (target, other):
            _click(window, "needle" + name)
            _click(window, "platter" + name)

        now = 342.95
        controller._tick()
        assert controller.decks[deck]["playing"]
        assert controller.decks[deck]["progress"] == pytest.approx(341.95 / 342)

        # The track ends after the last displayed frame, before stopping or lifting.
        now = 343.0 + end_offset
        _click(window, control + target)
        assert controller.decks[deck]["status"] == "Finished"
        assert controller.decks[deck]["progress"] == 1.0
        assert controller.decks[deck]["canLoad"]
        assert controller.decks[1 - deck]["playing"]
        assert controller.decks[1 - deck]["progress"] == pytest.approx((342 + end_offset) / 428)

        # Restarting the platter or lowering the needle never rewinds a finished track.
        _click(window, control + target)
        now += 1.0
        controller._tick()
        assert controller.decks[deck]["status"] == "Finished"
        assert controller.decks[deck]["progress"] == 1.0
        assert not _item(window, "load" + target + "_after-hours").isEnabled()
        assert not _item(window, "unload" + target).isEnabled()
        assert controller.decks[1 - deck]["progress"] == pytest.approx((343 + end_offset) / 428)
    finally:
        controller.close()
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
        controller.deleteLater()
        QTest.qWait(20)
