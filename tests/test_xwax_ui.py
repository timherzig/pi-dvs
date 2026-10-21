"""Real QML in engine mode, with slow Unix peers and a real export fixture."""

from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from test_import_ui import until
from test_ui import _click, _item
from test_ui import app as app
from test_xwax import Server, mutations
from test_xwax import pair as pair

from pi_dvs.app import create_window


def test_real_window_uses_imported_files_and_remains_responsive_to_slow_engine(app):
    with TemporaryDirectory(prefix="dvs-ui-", dir="/tmp") as directory:
        servers = [Server(Path(directory) / name) for name in ("a", "b")]
        qml, controller = create_window(sockets=tuple(s.path for s in servers))
        controller._cache = Path(directory) / "artwork"
        warnings = []
        qml.warnings.connect(lambda messages: warnings.extend(m.toString() for m in messages))
        try:
            assert qml.rootObjects()
            window = qml.rootObjects()[0]
            assert not controller.isSimulation
            assert controller.totalTracks == 0
            assert not _item(window, "vinylSimulator").isVisible()
            controller.openExport(str(Path("tests/fixtures/usb").resolve()), "pdb")
            until(lambda: not controller.importing and controller.totalTracks > 0)
            until(lambda: all(d["canLoad"] for d in controller.decks))
            track = controller._library.search("cafe")[0]
            _click(window, "loadA_" + track.id)
            until(lambda: controller.decks[0]["status"] == "Ready")
            assert controller.decks[0]["title"] == "Café 東京"
            assert str(track.audio_path) in mutations(servers[0])[0]
            assert "Vinyl tracking" == controller.decks[0]["transportMessage"]
            controller.setNeedleDown(0, True)
            controller.setPlatterSpinning(0, True)
            assert len(mutations(servers[0])) == 1
            assert not controller.decks[0]["needleDown"]
            servers[0].hang = True
            fired = []
            QTimer.singleShot(10, lambda: fired.append(True))
            search = _item(window, "searchField")
            search.setProperty("text", "cafe")
            QTest.qWait(80)
            assert fired and controller.trackCount == 1
            until(lambda: controller.decks[0]["status"] == "Disconnected")
            until(lambda: not _item(window, "unloadA").isEnabled())
            _click(window, "loadB_" + track.id)
            until(lambda: controller.decks[1]["status"] == "Ready")
            assert not warnings
        finally:
            controller.close()
            for window in qml.rootObjects():
                window.close()
            qml.deleteLater()
            controller.deleteLater()
            QTest.qWait(20)
            for server in servers:
                server.close()


def test_late_usb_preflight_cannot_load_into_a_reconnected_engine(app, pair, tmp_path, monkeypatch):
    from threading import Event

    from pi_dvs.library import Library
    from pi_dvs.model import Track
    from pi_dvs.presentation import Controller

    engine, (server, _) = pair
    track = Track("track", "Track", "", 1, audio_path=tmp_path / "track.wav")
    started, release = Event(), Event()

    def prepare(selected):
        started.set()
        release.wait(3)
        return selected.audio_path

    monkeypatch.setattr("pi_dvs.presentation.prepare_audio", prepare)
    controller = Controller(Library((track,), source_id="usb"), engine, tmp_path / "cache")
    try:
        generation = engine.decks[0].connection_generation
        controller.loadTrack(0, track.id)
        until(started.is_set)
        server.disconnect()
        until(lambda: engine.decks[0].connection_generation != generation)
        release.set()
        until(lambda: "reconnected" in controller.notice)
        assert not mutations(server)
        assert engine.decks[0].track is None
    finally:
        release.set()
        controller.close()


def test_progressive_timeline_and_rejected_incoming_load_preserve_current_track(
    app, pair, tmp_path, monkeypatch
):
    from pi_dvs.library import Library
    from pi_dvs.link.service import LinkService
    from pi_dvs.model import Status, Track
    from pi_dvs.presentation import Controller

    engine, (server, _) = pair
    old = Track("old", "Current", "", 120, audio_path=tmp_path / "old.aiff")
    new = Track(
        "old", "Incoming", "", 120, audio_path=tmp_path / "new.pidvs-stream", streaming=True
    )
    link = LinkService("test", tmp_path / "helper", tmp_path / "cache")
    monkeypatch.setattr(link, "start", lambda: None)
    controller = Controller(Library((old,), source_id="usb"), engine, link=link)
    try:
        engine.load(0, old)
        until(lambda: engine.decks[0].status == Status.READY)
        server.auto = False
        engine.load(0, new)
        controller._submitted[0] = new
        until(lambda: server.state.result == "PENDING")
        request = server.state.request_id
        controller._pin_audio()
        assert controller._submitted[0].audio_path == new.audio_path
        # Vinyl began moving before the handoff; native protection rejects it.
        server.override = (
            f"DVS2 STATE {request} LOCKED READY 1 1 1 1 20 120 1 {old.audio_path}\n"
        ).encode()
        until(lambda: not engine.decks[0].load_pending)
        controller._pin_audio()
        assert 0 not in controller._submitted
        assert engine.decks[0].track.id == old.id
        assert engine.decks[0].status == Status.PLAYING
        # A native progressive snapshot reports total and playable duration separately.
        server.override = (
            f"DVS2 STREAM_STATE {request} OK STREAMING 1 1 1 1 20 120 1 30 {old.audio_path}\n"
        ).encode()
        until(lambda: engine.decks[0].buffered_duration == 30)
        card = controller.decks[0]
        assert card["loadedProgress"] == 0.25
        assert card["progress"] == 20 / 120
        assert card["remaining"] == "01:40"
    finally:
        controller.close()


def test_reconnect_pending_handoff_keeps_orphan_until_native_resolves(
    app, pair, tmp_path, monkeypatch
):
    from pi_dvs.library import Library
    from pi_dvs.link.service import LinkService
    from pi_dvs.presentation import Controller

    engine, (server, _) = pair
    link = LinkService("test", tmp_path / "helper", tmp_path / "cache")
    monkeypatch.setattr(link, "start", lambda: None)
    orphan = link.streams.root / "prior-app"
    orphan.mkdir(parents=True)
    descriptor = orphan / "track.pidvs-stream"
    descriptor.touch()
    server.override = b"DVS2 STATE - PENDING EMPTY 0 1 1 0 0 0 0 \n"
    until(lambda: engine.decks[0].load_pending)
    controller = Controller(Library(()), engine, link=link)
    try:
        controller._pin_audio()
        QTest.qWait(300)
        assert descriptor.exists()
        server.override = b"DVS2 STATE - ERROR EMPTY 0 1 1 0 0 0 0 \n"
        until(lambda: not engine.decks[0].load_pending)
        controller._pin_audio()
        until(lambda: not descriptor.exists())
    finally:
        controller.close()


def test_real_qml_shows_playable_prefix_separately_from_playhead(app):
    with TemporaryDirectory(prefix="dvs-ui-", dir="/tmp") as directory:
        servers = [Server(Path(directory) / name) for name in ("a", "b")]
        qml, controller = create_window(sockets=tuple(s.path for s in servers))
        try:
            window = qml.rootObjects()[0]
            servers[
                0
            ].override = (
                b"DVS2 STREAM_STATE - OK STREAMING 1 1 1 1 20 120 1 30 /tmp/stream.pidvs-stream\n"
            )
            until(lambda: controller.decks[0]["loadedProgress"] == 0.25)
            timeline = _item(window, "timelineA")
            loaded = _item(window, "loadedAudioA")
            # Native state arrives before the GUI's 100 ms notification tick.
            # Assert the actual rendered binding instead of sleeping 50 ms.
            until(lambda: abs(loaded.width() - timeline.width() * 0.25) < 1)
            servers[
                0
            ].override = (
                b"DVS2 STREAM_STATE - OK STREAMING 1 1 1 1 20 120 1 60 /tmp/stream.pidvs-stream\n"
            )
            until(lambda: controller.decks[0]["loadedProgress"] == 0.5)
            until(lambda: abs(loaded.width() - timeline.width() * 0.5) < 1)
            assert controller.decks[0]["progress"] == 20 / 120
        finally:
            controller.close()
            for window in qml.rootObjects():
                window.close()
            qml.deleteLater()
            controller.deleteLater()
            QTest.qWait(20)
            for server in servers:
                server.close()
