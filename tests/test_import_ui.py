"""Import and CDJ-style browsing through the real QML controls, without audio hardware."""

import os
import shutil
from pathlib import Path
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QEventLoop, QMetaObject, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from test_ui import _click, _item

from pi_dvs.app import create_window
from pi_dvs.engine import DemoEngine
from pi_dvs.jobs import JobKind, Jobs
from pi_dvs.library import demo_library
from pi_dvs.presentation import Controller
from pi_dvs.rekordbox import import_library
from pi_dvs.rekordbox.records import ImportCancelled

FIXTURE = Path(__file__).parent / "fixtures/usb"


@pytest.fixture(scope="module")
def app():
    instance = QGuiApplication.instance() or QGuiApplication([])
    QQuickStyle.setStyle("Basic")
    return instance


def until(condition, timeout=5000):
    if condition():
        return
    # Use the real event loop so Python workers can run even during cold decoder
    # imports; repeated qWait calls can hold the GIL and starve those workers.
    loop = QEventLoop()
    poll = QTimer(loop)
    poll.setInterval(10)
    poll.timeout.connect(lambda: loop.quit() if condition() else None)
    deadline = QTimer(loop)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(timeout)
    loop.exec()
    poll.stop()
    deadline.stop()
    assert condition(), "Asynchronous operation did not complete"


@pytest.mark.parametrize("kind", ["pdb", "onelibrary"])
def test_select_export_navigate_playlists_search_and_load_through_qml(app, tmp_path, kind):
    engine, controller = create_window()
    controller._cache = tmp_path / "cache"
    warnings = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    try:
        window = engine.rootObjects()[0]
        QTest.qWait(80)
        # Exercise the same selectedFolder / accepted signal path as the native dialog.
        selector = window.findChild(QObject, "formatSelector")
        selector.setProperty("currentIndex", 1 if kind == "pdb" else 2)
        dialog = window.findChild(QObject, "exportDialog")
        _click(window, "openExport")
        QTest.qWait(50)
        dialog.setProperty("selectedFolder", QUrl.fromLocalFile(str(FIXTURE.resolve())))
        assert dialog.property("selectedFolder").isLocalFile()
        QMetaObject.invokeMethod(dialog, "accept")
        until(lambda: not controller.importing)
        assert not controller.isDemo
        assert controller.totalTracks == 3
        assert controller.trackCount == 3
        missing = controller._library.search("missing")[0]
        assert not _item(window, "loadA_" + missing.id).isEnabled()
        _click(window, "browse_playlists")
        _click(window, "entry_10")
        _click(window, "entry_11")
        _click(window, "entry_12")
        assert controller.browseTitle == "Café set"
        assert controller.trackCount == 3
        search = window.findChild(QObject, "searchField")
        search.setProperty("text", "cafe elise")
        assert controller.trackCount == 2  # repeated entry preserved, just like the export
        track = controller._library.search("cafe")[0]
        _click(window, "loadA_" + track.id)
        until(lambda: controller.decks[0]["status"] == "Ready")
        assert controller.decks[0]["title"] == "Café 東京"
        _click(window, "loadB_" + track.id)
        until(lambda: controller.decks[1]["status"] == "Ready")
        _click(window, "browseBack")
        assert controller.browseTitle == "Warm-up"
        assert controller.query == ""
        _click(window, "browse_artists")
        _click(window, "entry_Élise")
        assert controller.trackCount == 3
        assert controller.decks[0]["title"] == "Café 東京"
        assert not warnings
    finally:
        controller.close()
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
        controller.deleteLater()
        QTest.qWait(20)


def test_failed_import_retains_catalog_search_and_loaded_deck(app, tmp_path):
    controller = Controller(demo_library(), DemoEngine(), tmp_path / "cache")
    try:
        controller.openExport(str(FIXTURE.resolve()), "pdb")
        until(lambda: not controller.importing)
        original = controller._library
        track = original.search("cafe")[0]
        controller.loadTrack(0, track.id)
        until(lambda: controller.decks[0]["status"] == "Ready")
        controller.query = "cafe"
        controller.openExport(str(tmp_path / "not a USB"), "auto")
        until(lambda: not controller.importing)
        assert controller._library is original
        assert controller.trackCount == 1
        assert controller.query == "cafe"
        assert controller.decks[0]["title"] == track.title
        assert "No supported export" in controller.notice
    finally:
        controller.close()


def test_cancelled_and_superseded_imports_cannot_publish_stale_results(app, tmp_path, monkeypatch):
    started, release = Event(), Event()
    old = demo_library()
    new = import_library(FIXTURE.resolve(), tmp_path / "cache")

    def delayed(root, cache, **kwargs):
        if root.name == "old":
            started.set()
            release.wait(3)
            return old  # deliberately ignore cancellation to prove publication is guarded
        return new

    monkeypatch.setattr("pi_dvs.presentation.import_library", delayed)
    controller = Controller(old, DemoEngine(), tmp_path / "cache")
    try:
        controller.openExport("old", "auto")
        until(started.is_set)
        controller.openExport("new", "auto")
        until(lambda: not controller.importing)
        release.set()
        QTest.qWait(30)
        assert controller._library is new
        controller.openExport("old", "auto")
        controller.cancelImport()
        QTest.qWait(30)
        assert controller._library is new
        assert not controller.importing
        controller.refreshExport()
        until(lambda: not controller.importing)
    finally:
        release.set()
        controller.close()


def test_missing_file_after_import_and_unload_during_file_check(app, tmp_path, monkeypatch):
    usb = Path(shutil.copytree(FIXTURE, tmp_path / "USB"))
    library = import_library(usb, tmp_path / "cache")
    controller = Controller(library, DemoEngine(), tmp_path / "cache")
    track = library.tracks[0]
    try:
        track.audio_path.unlink()
        controller.loadTrack(0, track.id)
        until(lambda: bool(controller.notice))
        assert controller.decks[0]["status"] == "Empty"
        assert "Cannot load audio" in controller.notice
        release, started = Event(), Event()

        def delayed(selected):
            started.set()
            release.wait(3)
            return selected.audio_path

        monkeypatch.setattr("pi_dvs.presentation.prepare_audio", delayed)
        controller.loadTrack(1, track.id)
        until(started.is_set)
        controller.unload(1)
        release.set()
        QTest.qWait(30)
        assert controller.decks[1]["status"] == "Empty"
        controller.loadTrack(8, track.id)
        assert "Choose deck" in controller.notice
    finally:
        controller.close()


def test_job_boundary_reports_errors_and_ignores_closed_results(app, caplog):
    owner = QObject()
    jobs = Jobs(owner)
    results = []
    jobs.completed.connect(lambda key, result, error: results.append((key, result, error)))
    try:

        def expected(_):
            raise OSError("removed USB")

        jobs.submit(JobKind.IMPORT, expected)
        until(lambda: len(results) == 1)
        assert results[-1][2] == "removed USB"

        def unexpected(_):
            raise RuntimeError("bug")

        jobs.submit(JobKind.IMPORT, unexpected)
        until(lambda: len(results) == 2)
        assert "Unexpected" in results[-1][2]
        assert "RuntimeError: bug" in caplog.text

        def cancelled(_):
            raise ImportCancelled()

        jobs.submit(JobKind.IMPORT, cancelled)
        QTest.qWait(20)
        assert len(results) == 2
        jobs.close()
        jobs._receive(JobKind.IMPORT, 1, object(), "")
        assert len(results) == 2
    finally:
        jobs.close()


@pytest.mark.parametrize("deck, key", [(0, Qt.Key.Key_1), (1, Qt.Key.Key_2)])
@pytest.mark.parametrize("load_seconds", [0.35, 0.6])
def test_keyboard_load_uses_displayed_track_before_any_browsing(
    app, monkeypatch, deck, key, load_seconds
):
    monkeypatch.setattr(DemoEngine, "LOAD_SECONDS", load_seconds)
    engine, controller = create_window()
    try:
        window = engine.rootObjects()[0]
        QTest.qWait(100)
        model = controller.libraryModel
        title_role = next(role for role, name in model.roleNames().items() if name == b"trackTitle")
        selected_row = next(
            row
            for row in range(model.rowCount())
            if model.data(model.index(row), title_role) == "Tidal Memory"
        )
        track_list = window.findChild(QObject, "trackList")
        track_list.setProperty("currentIndex", selected_row)
        track_list.forceActiveFocus()
        QTest.keyClick(window, key, Qt.KeyboardModifier.ControlModifier)
        until(lambda: controller.decks[deck]["status"] == "Ready")
        assert controller.decks[deck]["title"] == "Tidal Memory"
        assert controller.decks[deck]["status"] == "Ready"
        assert controller.decks[1 - deck]["status"] == "Empty"
    finally:
        controller.close()
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
        controller.deleteLater()
        QTest.qWait(20)


@pytest.mark.parametrize("previous_usb", [False, True])
def test_format_switch_during_import_keeps_pending_usb(app, tmp_path, monkeypatch, previous_usb):
    usb_a = Path(shutil.copytree(FIXTURE, tmp_path / "USB A"))
    usb_b = Path(shutil.copytree(FIXTURE, tmp_path / "USB B"))
    started, release, returned = Event(), Event(), Event()
    calls = []

    def delayed(root, cache, **kwargs):
        calls.append((root, kwargs["format_choice"]))
        if root == usb_b and kwargs["format_choice"] == "auto":
            started.set()
            release.wait(5)
            try:
                # Simulate a read that cannot be interrupted. Its late result
                # must not replace the newly selected format for the same USB.
                return import_library(root, cache, format_choice="auto")
            finally:
                returned.set()
        return import_library(root, cache, **kwargs)

    monkeypatch.setattr("pi_dvs.presentation.import_library", delayed)
    engine, controller = create_window()
    controller._cache = tmp_path / "cache"
    try:
        window = engine.rootObjects()[0]
        QTest.qWait(80)
        if previous_usb:
            controller.openExport(str(usb_a), "auto")
            until(lambda: not controller.importing)
            assert controller.libraryName.startswith("USB A")
        controller.openExport(str(usb_b), "auto")
        until(started.is_set)
        assert controller.importing
        # Exercise the real QML ComboBox activation while the USB read is held.
        _click(window, "formatSelector")
        QTest.keyClick(window, Qt.Key.Key_End)
        QTest.keyClick(window, Qt.Key.Key_Return)
        selector = window.findChild(QObject, "formatSelector")
        assert selector.property("currentValue") == "onelibrary"
        until(lambda: not controller.importing)
        assert calls == ([(usb_a, "auto")] if previous_usb else []) + [
            (usb_b, "auto"),
            (usb_b, "onelibrary"),
        ]
        assert controller.libraryName == "USB B · OneLibrary"
        assert all(track.media_root == usb_b for track in controller._library.tracks)
        release.set()
        until(returned.is_set)
        QTest.qWait(30)
        assert controller.libraryName == "USB B · OneLibrary"
        controller.refreshExport()
        until(lambda: not controller.importing)
        assert calls[-1] == (usb_b, "onelibrary")
    finally:
        release.set()
        controller.close()
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
        controller.deleteLater()
        QTest.qWait(20)
