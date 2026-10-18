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
