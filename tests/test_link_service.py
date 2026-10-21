import shutil
import time
from pathlib import Path
from threading import Event, Thread

import pytest
from link_peer import Peer

from pi_dvs.link.nfs import Client
from pi_dvs.link.service import LinkService
from pi_dvs.rekordbox.records import ImportCancelled

FIXTURE = Path(__file__).parent / "fixtures/usb"


def message(usb=True, generation="one"):
    return dict(
        address="127.0.0.1",
        players=[
            dict(
                number=1,
                address="127.0.0.1",
                mac=[1, 2, 3, 4, 5, 6],
                usb=usb,
                generation=generation,
            )
        ],
    )


def service(tmp_path):
    return LinkService("test", tmp_path / "helper", tmp_path / "cache")


def test_local_usb_removal_replacement_and_cached_loaded_audio(tmp_path):
    usb = Path(shutil.copytree(FIXTURE, tmp_path / "USB"))
    link = service(tmp_path)
    first = link.import_local(usb, "pdb", Event())
    link.accept_local(first.source_id)
    track = first.search("cafe")[0]
    link.audio.protect((track,))
    cached = link.prepare(track, Event())
    original = cached.read_bytes()
    usb.rename(tmp_path / "removed")
    link._watch_local()
    assert not link.available(track)
    assert link._command is None
    assert cached.read_bytes() == original
    with pytest.raises(ImportCancelled):
        link.prepare(track, Event())
    shutil.copytree(FIXTURE, usb)
    (usb / track.relative_path).write_bytes(b"replacement audio")
    link._watch_local()
    view = link.sources.views()[0]
    assert view.library.source_id != first.source_id
    replacement = view.library.search("cafe")[0]
    new_cached = link.prepare(replacement, Event())
    assert new_cached != cached
    assert new_cached.read_bytes() == b"replacement audio"
    assert cached.read_bytes() == original
    assert link._command["tracks"]
    link.close()


def patch_client(monkeypatch, peer):
    class WiredClient(Client):
        def __init__(self, address, **kwargs):
            super().__init__(address, interval=0, timeout=0.05, **kwargs)

        def mount(self, ip, portmap_port=111):
            super().mount(ip, peer.port)

    monkeypatch.setattr("pi_dvs.link.service.Client", WiredClient)


def test_remote_catalog_download_reconnect_same_ids_and_protected_cache(tmp_path, monkeypatch):
    files = {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }
    with Peer(files=files, sparse=True) as peer:
        patch_client(monkeypatch, peer)
        link = service(tmp_path)
        link.update_peers(message(), "process1")
        key = link.sources.views()[0].media.key
        library = link.catalog(key, Event())
        track = library.search("cafe")[0]
        assert track.available and track.audio_path is None
        assert library.search("missing")[0].available  # presence is checked at selection
        link.audio.protect((track,))
        cached = link.prepare(track, Event())
        original = cached.read_bytes()
        assert original == files["/" + track.relative_path]
        assert link.catalog(key, Event()) is library
        link.update_peers(message(False), "process1")
        assert not link.available(track)
        files["/" + track.relative_path] = b"different bytes with reused track IDs"
        link.update_peers(message(True, "two"), "process1")
        new = link.catalog(key, Event())
        replacement = new.search("cafe")[0]
        assert replacement.id != track.id
        other = link.prepare(replacement, Event())
        assert other.read_bytes() == files["/" + track.relative_path]
        assert cached.read_bytes() == original
        assert other != cached
        link.refresh_source(key)
        assert not link.available(replacement)
        refreshed = link.catalog(key, Event())
        assert refreshed.source_id != new.source_id
        link.update_peers(dict(address="127.0.0.1", players=[]), "process1")
        assert link.sources.view(key).media.cancelled.is_set()


def test_usb_stop_during_audio_read_cancels_without_partial_publication(tmp_path, monkeypatch):
    files = {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }
    with Peer(files=files) as peer:
        patch_client(monkeypatch, peer)
        link = service(tmp_path)
        link.update_peers(message(), "process")
        key = link.sources.views()[0].media.key
        track = link.catalog(key, Event()).search("cafe")[0]

        def unplug(path):
            if path == "/" + track.relative_path:
                link.update_peers(message(False), "process")

        peer.read_hook = unplug
        with pytest.raises(ImportCancelled):
            link.prepare(track, Event())
        assert not list(link.audio.root.iterdir())


def test_waiting_second_deck_can_cancel_without_starting_another_transfer(tmp_path):
    link = service(tmp_path)
    from pi_dvs.link.media import Cancel

    link._transfers.acquire()
    event = Event()
    finished = Event()

    def waiting():
        try:
            with link._transfer(Cancel(event)):
                pytest.fail("Cancelled queued transfer started")
        except ImportCancelled:
            finished.set()

    thread = Thread(target=waiting)
    thread.start()
    event.set()
    assert finished.wait(0.3)
    link._transfers.release()
    thread.join(1)


def test_helper_failure_is_reported_and_shutdown_is_bounded(tmp_path):
    link = service(tmp_path)
    link.start()
    deadline = time.monotonic() + 3
    while "unavailable" not in link.status and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "unavailable" in link.status
    link.close()
    link._worker.join(2)
    assert not link._worker.is_alive()


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"address": "x", "players": [{}]},
        {"address": "x", "players": [{"address": "x", "mac": []}]},
    ],
)
def test_malformed_helper_snapshots_fail_closed(tmp_path, snapshot):
    with pytest.raises(ValueError):
        service(tmp_path).update_peers(snapshot, "process")


def test_unchanged_local_browser_round_trip_does_not_restart_server(tmp_path):
    usb = Path(shutil.copytree(FIXTURE, tmp_path / "USB"))
    link = service(tmp_path)
    first = link.import_local(usb, "pdb", Event())
    assert not link.sources.views()  # imports are staged until accepted
    link.accept_local(first.source_id)
    revision = link._command_revision
    again = link.import_local(usb, "pdb", Event())
    link.accept_local(again.source_id)
    assert again.source_id == first.source_id
    assert link._command_revision == revision


def test_cancelled_import_cannot_replace_accepted_same_root_format(tmp_path):
    usb = Path(shutil.copytree(FIXTURE, tmp_path / "USB"))
    link = service(tmp_path)
    event = Event()
    old = link.import_local(usb, "pdb", event)
    newer = link.import_local(usb, "onelibrary", Event())
    link.accept_local(newer.source_id)
    event.set()
    with pytest.raises(ImportCancelled):
        link.accept_local(old.source_id)
    assert link.sources.views()[0].library is newer
    assert link.available(newer.tracks[0])


def test_old_watcher_cannot_steal_a_newer_local_selection(tmp_path, monkeypatch):
    a = Path(shutil.copytree(FIXTURE, tmp_path / "A"))
    b = Path(shutil.copytree(FIXTURE, tmp_path / "B"))
    link = service(tmp_path)
    first = link.import_local(a, "pdb", Event())
    link.accept_local(first.source_id)
    link.sources.disconnect(link.sources.media(first.source_id).key)
    original = link.import_local

    def delayed(root, choice, event):
        staged = original(root, choice, event)
        newer = original(b, "pdb", Event())
        link.accept_local(newer.source_id)
        return staged

    monkeypatch.setattr(link, "import_local", delayed)
    link._watch_local()
    assert link._locals[link._selected_local][0] == b
    assert link._command["root"] == str(b)


@pytest.mark.parametrize("same_root", [False, True])
def test_delayed_watcher_error_cannot_disconnect_newer_selection(tmp_path, monkeypatch, same_root):
    from pi_dvs.link.catalog import local_token

    a = Path(shutil.copytree(FIXTURE, tmp_path / "A"))
    b = a if same_root else Path(shutil.copytree(FIXTURE, tmp_path / "B"))
    link = service(tmp_path)
    first = link.import_local(a, "pdb", Event())
    link.accept_local(first.source_id)
    newer = link.import_local(b, "onelibrary", Event())
    old = link.sources.media(first.source_id)
    expected = None

    def delayed(path):
        nonlocal expected
        link.accept_local(newer.source_id)
        expected = link._command
        if same_root:
            return local_token(path) + "changed"
        raise FileNotFoundError("A unplugged")

    monkeypatch.setattr("pi_dvs.link.service.local_token", delayed)
    if same_root:
        monkeypatch.setattr(link, "import_local", lambda *args: newer)
    link._watch_local()
    assert link._command is expected
    assert link.available(newer.tracks[0])
    assert old.cancelled.is_set() if same_root else not link.available(first.tracks[0])
    link.close()


def test_unavailable_cache_reports_error_instead_of_losing_supervisor(tmp_path):
    blocked = tmp_path / "cache"
    blocked.write_bytes(b"a file cannot be a cache directory")
    link = service(tmp_path)
    link.start()
    link._worker.join(2)
    assert not link._worker.is_alive()
    assert "unavailable" in link.status
    assert "cache" in link.status
    link.close()


def test_progressive_remote_audio_starts_early_and_usb_loss_never_completes_cache(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from test_stream_audio import aiff

    from pi_dvs.stream_audio import read_object

    data, _ = aiff(frames=44100 * 20)
    files = {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }
    files["/test.aiff"] = data
    paused, release = Event(), Event()
    with Peer(files=files, sparse=True) as peer:
        patch_client(monkeypatch, peer)
        link = service(tmp_path)
        try:
            link.update_peers(message(), "process")
            key = link.sources.views()[0].media.key
            track = replace(
                link.catalog(key, Event()).search("cafe")[0],
                relative_path="/test.aiff",
                duration=20,
                sample_rate=44100,
                bit_depth=16,
            )
            link.streams.protect((), authoritative=True, preparing=(track.id,))
            link.audio.protect((track,))

            def hold(path):
                if path == "/test.aiff" and peer.reads[-1][1] >= 2 * 1024 * 1024:
                    paused.set()
                    assert release.wait(3)

            peer.read_hook = hold
            prepared = link.prepare_progressive(track, Event())
            assert prepared.streaming and prepared.duration == 20
            attached = replace(track, audio_path=prepared.path, streaming=True)
            link.streams.protect((attached,), authoritative=True)
            assert paused.wait(1)
            assert not list(link.audio.root.glob(".audio-*"))
            assert read_object(prepared.path.parent / "state.json")["status"] == "loading"
            link.update_peers(message(False), "process")
            release.set()
            deadline = time.monotonic() + 2
            while link.streams.state(track).status != "failed" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert link.streams.state(track).status == "failed"
            assert not list(link.audio.root.glob(".audio-*"))
            assert not list(link.audio.root.glob(".partial-*"))
            assert (prepared.path.parent / "audio.aiff").stat().st_size >= 10 * 44100 * 4
        finally:
            release.set()
            link.close()


def test_local_reconnect_retires_catalogs_but_preserves_loaded_cache(tmp_path):
    usb = Path(shutil.copytree(FIXTURE, tmp_path / "USB"))
    link = service(tmp_path)
    first = link.import_local(usb, "pdb", Event())
    link.accept_local(first.source_id)
    track = first.search("cafe")[0]
    link.audio.protect((track,))
    cached = link.prepare(track, Event())
    original = cached.read_bytes()
    for _ in range(5):
        usb.rename(tmp_path / "removed")
        link._watch_local()
        (tmp_path / "removed").rename(usb)
        link._watch_local()
        assert len(link._locals) == 1
        assert not link._staged
        assert cached.read_bytes() == original
    assert not link.available(track)
    current = link.sources.views()[0]
    assert link.accept_local(current.media.source_id) is current.media
    link.close()


def test_cancelled_staged_catalogs_are_retired(tmp_path):
    link = service(tmp_path)
    cancelled = []
    for _ in range(5):
        event = Event()
        library = link.import_local(FIXTURE, "pdb", event)
        event.set()
        cancelled.append(library.source_id)
    # A new successful import collects abandoned preparations too.
    fresh = link.import_local(FIXTURE, "pdb", Event())
    link.accept_local(fresh.source_id)
    assert len(link._locals) == 1
    assert not link._staged
    for source_id in cancelled:
        with pytest.raises(ImportCancelled):
            link.accept_local(source_id)
    link.close()


def test_uncached_catalog_opens_during_other_cdj_audio_download(tmp_path, monkeypatch):
    files = {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }
    started, release, opened = Event(), Event(), Event()
    failures = []
    with Peer(files=files) as peer:
        patch_client(monkeypatch, peer)
        original = Client.download

        def paused_audio(client, path, *args, **kwargs):
            if path != "/PIONEER/rekordbox/export.pdb":
                started.set()
                assert release.wait(3)
            return original(client, path, *args, **kwargs)

        monkeypatch.setattr(Client, "download", paused_audio)
        link = service(tmp_path)
        snapshot = message()
        snapshot["players"].append(dict(snapshot["players"][0], number=2, mac=[6] * 6))
        link.update_peers(snapshot, "test")
        keys = [v.media.key for v in link.sources.views()]
        track = link.catalog(keys[0], Event()).search("cafe")[0]

        def audio():
            try:
                link.prepare(track, Event())
            except Exception as error:
                failures.append(error)

        def catalog():
            try:
                assert link.catalog(keys[1], Event()).tracks
                opened.set()
            except Exception as error:
                failures.append(error)

        a, b = Thread(target=audio), Thread(target=catalog)
        a.start()
        assert started.wait(1)
        b.start()
        try:
            assert opened.wait(1), "Other USB catalog waited for the whole audio download"
            assert not release.is_set()
        finally:
            release.set()
            a.join(3)
            b.join(3)
            link.close()
        assert not a.is_alive() and not b.is_alive()
        assert not failures


def test_catalog_is_loadable_as_soon_as_it_is_published(tmp_path, monkeypatch):
    files = {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }
    with Peer(files=files) as peer:
        patch_client(monkeypatch, peer)
        link = service(tmp_path)
        link.update_peers(message(), "test")
        original = link.sources.publish
        prepared = []

        def publish(media, library):
            original(media, library)
            # Another caller can see the published library immediately.
            track = library.search("cafe")[0]
            prepared.append(link.prepare(track, Event()))

        monkeypatch.setattr(link.sources, "publish", publish)
        library = link.catalog(link.sources.views()[0].media.key, Event())
        assert prepared[0].read_bytes() == files["/" + library.search("cafe")[0].relative_path]
        assert link.available(library.tracks[0])
        link.close()
