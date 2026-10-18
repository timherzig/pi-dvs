"""Real QML source selection, cached deck loads, and USB recovery over fake UDP."""

import os
import shutil
from pathlib import Path
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from link_peer import Peer
from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from test_import_ui import until
from test_link_service import message, patch_client
from test_ui import _click, _item

from pi_dvs.app import create_window
from pi_dvs.link.service import LinkService

FIXTURE = Path(__file__).parent / "fixtures/usb"


@pytest.fixture(scope="module")
def app():
    instance = QGuiApplication.instance() or QGuiApplication([])
    QQuickStyle.setStyle("Basic")
    return instance


def close(engine, controller):
    controller.close()
    for window in engine.rootObjects():
        window.close()
    engine.deleteLater()
    controller.deleteLater()
    QTest.qWait(20)


def test_qml_switches_sources_and_keeps_loaded_audio_through_usb_reconnect(
    app, tmp_path, monkeypatch
):
    files = {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }
    usb = Path(shutil.copytree(FIXTURE, tmp_path / "Local USB"))
    link = LinkService("test", tmp_path / "helper", tmp_path / "cache")
    monkeypatch.setattr(link, "start", lambda: None)
    with Peer(files=files, sparse=True) as peer:
        patch_client(monkeypatch, peer)
        engine, controller = create_window(link=link)
        warnings = []
        engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
        try:
            window = engine.rootObjects()[0]
            controller.openExport(str(usb), "pdb")
            until(lambda: not controller.importing)
            local_library = controller._library
            track = local_library.search("cafe")[0]
            _click(window, "loadA_" + track.id)
            until(lambda: controller.decks[0]["status"] == "Ready")
            local_cached = controller._engine.decks[0].track.audio_path
            assert local_cached.parent == link.audio.root
            # Discovery cannot steal the current browsing state or restart sharing.
            controller.query = "cafe"
            serving_revision = link._command_revision
            link.update_peers(message(), "helper")
            until(lambda: window.findChild(QObject, "sourceSelector").property("count") == 2)
            assert controller._library is local_library and controller.query == "cafe"
            assert link._command_revision == serving_revision
            _click(window, "sourceSelector")
            QTest.keyClick(window, Qt.Key.Key_End)
            QTest.keyClick(window, Qt.Key.Key_Return)
            until(lambda: not controller.importing and controller.libraryName.startswith("CDJ 1"))
            assert not window.findChild(QObject, "formatSelector").isEnabled()
            remote = controller._library.search("cafe")[0]
            _click(window, "loadB_" + remote.id)
            until(lambda: controller.decks[1]["status"] == "Ready")
            until(lambda: bool(controller.decks[1]["artwork"]))
            cover = Path(QUrl(controller.decks[1]["artwork"]).toLocalFile())
            assert cover.read_bytes() == files[remote.artwork_path]
            cached = controller._engine.decks[1].track.audio_path
            assert cached.read_bytes() == files["/" + remote.relative_path]
            link.update_peers(message(False), "helper")
            until(lambda: not controller._library.search("cafe")[0].available)
            assert not _item(window, "loadB_" + remote.id).isEnabled()
            assert cached.exists() and local_cached.exists() and cover.exists()
            assert controller.decks[1]["artwork"] == cover.as_uri()
            assert controller.decks[1]["title"] == remote.title
            assert link._command_revision == serving_revision
            files["/" + remote.relative_path] = b"replacement USB content"
            link.update_peers(message(True, "replacement"), "helper")
            until(
                lambda: (
                    not controller.importing and controller._library.source_id != remote.source_id
                )
            )
            fresh = controller._library.search("cafe")[0]
            assert fresh.id != remote.id
            _click(window, "loadB_" + fresh.id)
            until(
                lambda: (
                    controller.decks[1]["status"] == "Ready"
                    and controller._engine.decks[1].track.id == fresh.id
                )
            )
            assert (
                controller._engine.decks[1].track.audio_path.read_bytes()
                == b"replacement USB content"
            )
            # Return to the local view without restarting the CDJ server.
            _click(window, "sourceSelector")
            QTest.keyClick(window, Qt.Key.Key_Home)
            QTest.keyClick(window, Qt.Key.Key_Return)
            until(lambda: not controller.importing and controller.localSource)
            assert link._command_revision == serving_revision
            assert not warnings
        finally:
            close(engine, controller)


def test_pending_load_is_cancelled_on_usb_stop_and_local_reinsert_updates_view(
    app, tmp_path, monkeypatch
):
    usb = Path(shutil.copytree(FIXTURE, tmp_path / "USB"))
    link = LinkService("test", tmp_path / "helper", tmp_path / "cache")
    monkeypatch.setattr(link, "start", lambda: None)
    engine, controller = create_window(link=link)
    started, release = Event(), Event()
    try:
        controller.openExport(str(usb), "pdb")
        until(lambda: not controller.importing)
        track = controller._library.search("cafe")[0]
        original = link.prepare

        def delayed(track, event):
            started.set()
            release.wait(3)
            return original(track, event)

        monkeypatch.setattr(link, "prepare", delayed)
        controller.loadTrack(0, track.id)
        until(started.is_set)
        usb.rename(tmp_path / "removed")
        link._watch_local()
        until(lambda: not controller._preparing)
        assert "cancelled" in controller.notice
        release.set()
        QTest.qWait(30)
        assert controller.decks[0]["status"] == "Empty"
        shutil.copytree(FIXTURE, usb)
        link._watch_local()
        until(lambda: not controller.importing and controller._library.source_id != track.source_id)
        assert all(t.source_id != track.source_id for t in controller._library.tracks)
        assert link._command is not None
        controller.selectSource("unknown")
        assert not controller.importing
    finally:
        release.set()
        close(engine, controller)


def test_cover_work_cannot_delay_or_replace_a_new_audio_load(app, tmp_path, monkeypatch):
    from threading import Event

    from pi_dvs.jobs import JobKind
    from pi_dvs.link.media import Cancel

    assert JobKind.COVER_A != JobKind.DECK_A
    assert JobKind.COVER_B != JobKind.DECK_B
    files = {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }
    link = LinkService("test", tmp_path / "helper", tmp_path / "cache")
    monkeypatch.setattr(link, "start", lambda: None)
    started, released, cancelled = Event(), Event(), Event()

    def slow_cover(track, event):
        if started.is_set():
            return None
        with link._transfer(Cancel(event)):
            started.set()
            # Hold the same gate as a slow real cover, until audio cancels it.
            if event.wait(3):
                cancelled.set()
        released.wait(3)
        # Simulate a late result arriving after its job was cancelled.
        return tmp_path / "stale-cover.jpg"

    monkeypatch.setattr(link, "cover", slow_cover)
    with Peer(files=files) as peer:
        patch_client(monkeypatch, peer)
        engine, controller = create_window(link=link)
        try:
            link.update_peers(message(), "process")
            controller.selectSource(link.sources.views()[0].media.key)
            until(lambda: not controller.importing)
            track = controller._library.search("cafe")[0]
            controller.loadTrack(0, track.id)
            until(started.is_set)
            until(lambda: controller.decks[0]["status"] == "Ready")
            first = controller._engine.decks[0].track.audio_path
            controller.loadTrack(1, track.id)
            until(cancelled.is_set)
            until(lambda: controller.decks[1]["status"] == "Ready")
            assert not released.is_set()
            released.set()
            QTest.qWait(100)
            assert controller._engine.decks[0].track.audio_path == first
            assert not controller.decks[0]["artwork"]
            assert not controller.notice
        finally:
            released.set()
            close(engine, controller)


def test_covers_follow_confirmed_xwax_load_and_missing_cover_is_not_polled(
    app, tmp_path, monkeypatch
):
    from tempfile import TemporaryDirectory

    from test_xwax import Server, mutations

    files = {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }
    link = LinkService("test", tmp_path / "helper", tmp_path / "cache")
    monkeypatch.setattr(link, "start", lambda: None)
    with (
        Peer(files=files) as peer,
        TemporaryDirectory(prefix="dvs-cover-", dir="/tmp") as directory,
    ):
        patch_client(monkeypatch, peer)
        servers = [Server(Path(directory) / name) for name in ("a", "b")]
        engine, controller = create_window(sockets=tuple(s.path for s in servers), link=link)
        try:
            link.update_peers(message(), "process")
            controller.selectSource(link.sources.views()[0].media.key)
            until(lambda: not controller.importing and controller.decks[0]["canLoad"])
            track = controller._library.search("cafe")[0]
            controller.loadTrack(0, track.id)
            until(lambda: controller.decks[0]["status"] == "Ready")
            until(lambda: bool(controller.decks[0]["artwork"]))
            assert len(mutations(servers[0])) == 1  # Covers must never reload audio.
            controller.unload(0)
            until(lambda: controller.decks[0]["status"] == "Empty")
            seen = []
            monkeypatch.setattr(link, "cover", lambda t, e: seen.append(t.id))
            controller._model._covers.clear()
            controller.loadTrack(0, track.id)
            until(lambda: len(seen) > 0)
            QTest.qWait(400)
            assert seen == [track.id]
        finally:
            close(engine, controller)
            for server in servers:
                server.close()


def test_reloading_an_evicted_cover_fetches_it_again(app, tmp_path, monkeypatch):
    from threading import Event

    from test_link_covers import picture

    from pi_dvs.link.media import Cancel

    files = {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }
    link = LinkService("test", tmp_path / "helper", tmp_path / "cache")
    monkeypatch.setattr(link, "start", lambda: None)
    with Peer(files=files) as peer:
        patch_client(monkeypatch, peer)
        engine, controller = create_window(link=link)
        try:
            link.update_peers(message(), "process")
            controller.selectSource(link.sources.views()[0].media.key)
            until(lambda: not controller.importing)
            track = controller._library.search("cafe")[0]
            controller.loadTrack(0, track.id)
            until(lambda: bool(controller.decks[0]["artwork"]))
            cover = Path(QUrl(controller.decks[0]["artwork"]).toLocalFile())
            controller.unload(0)
            controller._tick()
            replacement = picture("red")
            link.covers.limit = max(len(replacement), cover.stat().st_size)
            link.covers.store(("g", "another"), replacement, Cancel(Event()))
            assert not cover.exists()
            controller.loadTrack(0, track.id)
            until(lambda: bool(controller.decks[0]["artwork"]) and cover.exists())
        finally:
            close(engine, controller)
