"""Remote cover fidelity, failure isolation, cancellation and bounded cache behavior."""

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Event

import pytest
from link_peer import Peer
from PIL import Image
from test_link_service import FIXTURE, message, patch_client, service

from pi_dvs.link.covers import MAX_COVER_BYTES, CoverCancel, Covers
from pi_dvs.link.media import Cancel
from pi_dvs.rekordbox.records import ImportCancelled


def picture(color):
    output = BytesIO()
    Image.new("RGB", (20, 20), color).save(output, "PNG")
    return output.getvalue()


def files():
    return {
        "/" + p.relative_to(FIXTURE).as_posix(): p.read_bytes()
        for p in FIXTURE.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("preferred", ["valid", "broken", "missing", "oversized"])
def test_cover_prefers_decodable_high_resolution_and_reuses_cached_copy(
    tmp_path, monkeypatch, preferred
):
    exported = files()
    with Peer(files=exported, sparse=True) as peer:
        patch_client(monkeypatch, peer)
        link = service(tmp_path)
        link.update_peers(message(), "one")
        track = link.catalog(link.sources.views()[0].media.key, Event()).search("cafe")[0]
        art = Path(track.artwork_path)
        hi = str(art.with_stem(art.stem + "_m"))
        if preferred != "missing":
            exported[hi] = {
                "valid": picture("red"),
                "broken": b"broken jpeg",
                "oversized": b"x" * (MAX_COVER_BYTES + 1),
            }[preferred]
        cover = link.cover(track, Event())
        assert cover and cover.is_relative_to(link.covers.root)
        assert cover.read_bytes() == exported[hi if preferred == "valid" else str(art)]
        reads = len(peer.reads)
        assert link.cover(track, Event()) == cover
        assert len(peer.reads) == reads
        assert link.prepare(track, Event()).read_bytes() == exported["/" + track.relative_path]
        link.close()


def test_bad_missing_or_unsafe_cover_does_not_prevent_audio(tmp_path, monkeypatch):
    exported = files()
    with Peer(files=exported) as peer:
        patch_client(monkeypatch, peer)
        link = service(tmp_path)
        link.update_peers(message(), "one")
        track = link.catalog(link.sources.views()[0].media.key, Event()).search("cafe")[0]
        for value in ("", "../../outside.jpg", "/absent", track.artwork_path):
            if value == track.artwork_path:
                exported[value] = b"not an image"
            assert link.cover(replace(track, artwork_path=value), Event()) is None
        assert not link.covers.root.exists()
        assert link.prepare(track, Event()).is_file()
        link.close()


def test_usb_removal_during_cover_cancels_and_reinsert_gets_fresh_art(tmp_path, monkeypatch):
    exported = files()
    with Peer(files=exported) as peer:
        patch_client(monkeypatch, peer)
        link = service(tmp_path)
        link.update_peers(message(), "one")
        key = link.sources.views()[0].media.key
        track = link.catalog(key, Event()).search("cafe")[0]
        peer.read_hook = lambda path: (
            link.update_peers(message(False), "one") if path == track.artwork_path else None
        )
        with pytest.raises(ImportCancelled):
            link.cover(track, Event())
        assert not list(link.cache_root.glob("cover-*"))
        assert not link.covers.root.exists()
        peer.read_hook = None
        exported[track.artwork_path] = picture("blue")
        link.update_peers(message(True, "reinserted"), "one")
        replacement = link.catalog(key, Event()).search("cafe")[0]
        assert replacement.source_id != track.source_id
        cover = link.cover(replacement, Event())
        assert cover.read_bytes() == picture("blue")
        link.update_peers(message(False), "one")
        assert cover.read_bytes() == picture("blue")
        link.close()


def test_optional_cover_deadline_does_not_fail_audio(tmp_path, monkeypatch):
    import pi_dvs.link.service as module

    exported = files()
    with Peer(files=exported) as peer:
        patch_client(monkeypatch, peer)
        link = service(tmp_path)
        link.update_peers(message(), "one")
        track = link.catalog(link.sources.views()[0].media.key, Event()).search("cafe")[0]
        monkeypatch.setattr(module, "CoverCancel", lambda event: CoverCancel(event, 0))
        assert link.cover(track, Event()) is None
        assert link.prepare(track, Event()).is_file()
        link.close()


def test_cover_cache_is_bounded_and_never_evicts_a_loaded_cover(tmp_path):
    red, blue, green = picture("red"), picture("blue"), picture("green")
    cache = Covers(tmp_path, len(red) + len(blue) + len(green) - 1)
    cancel = Cancel(Event())
    first = cache.store(("generation", "a"), red, cancel)
    second = cache.store(("generation", "b"), blue, cancel)
    cache.protect((first,))
    third = cache.store(("generation", "c"), green, cancel)
    assert first.exists() and third.exists() and not second.exists()
    assert cache.find(("generation", "b")) is None
    assert sum(p.stat().st_size for p in tmp_path.iterdir()) <= cache.limit
    assert cache.store(("g", "broken"), b"bad", cancel) is None
    assert cache.store(("g", "large"), b"x" * (MAX_COVER_BYTES + 1), cancel) is None
    cache.protect((first, third))
    assert cache.store(("g", "full"), blue, cancel) is None
    event = Event()
    event.set()
    with pytest.raises(ImportCancelled):
        cache.store(("g", "cancelled"), blue, Cancel(event))
    assert not list(tmp_path.glob(".cover-*"))


def test_cover_pixels_are_bounded_before_decode(tmp_path, monkeypatch):
    monkeypatch.setattr("pi_dvs.link.covers.MAX_ARTWORK_PIXELS", 100)
    assert Covers(tmp_path).store(("g", "a"), picture("red"), Cancel(Event())) is None
    assert not list(tmp_path.iterdir())


def test_slow_cache_write_does_not_block_gui_pins(tmp_path, monkeypatch):
    from threading import Thread

    import pi_dvs.link.covers as module

    started, release, pinned = Event(), Event(), Event()
    original = module.NamedTemporaryFile

    def slow_write(**kwargs):
        started.set()
        release.wait(3)
        return original(**kwargs)

    monkeypatch.setattr(module, "NamedTemporaryFile", slow_write)
    cache = Covers(tmp_path)
    worker = Thread(target=lambda: cache.store(("g", "a"), picture("red"), Cancel(Event())))
    pin = Thread(target=lambda: (cache.protect(()), pinned.set()))
    worker.start()
    try:
        assert started.wait(1)
        pin.start()
        assert pinned.wait(0.2), "GUI pins blocked behind cover file I/O"
    finally:
        release.set()
        worker.join(3)
        pin.join(3)


def test_cover_deadline_starts_after_waiting_for_progressive_audio(tmp_path, monkeypatch):
    import time
    from contextlib import contextmanager
    from threading import Thread

    import pi_dvs.link.service as module

    # Keep the real cancellation/deadline and transfer gate, with a short budget.
    monkeypatch.setattr(module, "CoverCancel", lambda parent: CoverCancel(parent, seconds=0.2))
    exported = files()
    with Peer(files=exported, sparse=True) as peer:
        patch_client(monkeypatch, peer)
        link = service(tmp_path)
        link.update_peers(message(), "one")
        track = link.catalog(link.sources.views()[0].media.key, Event()).search("cafe")[0]
        results = []
        waiting = Event()

        original_transfer = link._transfer

        @contextmanager
        def queued(cancelled):
            waiting.set()
            with original_transfer(cancelled):
                yield

        monkeypatch.setattr(link, "_transfer", queued)

        def fetch():
            results.append(link.cover(track, Event()))

        worker = Thread(target=fetch, daemon=True)
        try:
            # A progressive producer owns this gate beyond the cover's budget.
            with original_transfer(Cancel(Event())):
                worker.start()
                assert waiting.wait(1)
                time.sleep(0.35)
            worker.join(3)
            assert not worker.is_alive()
            assert results and results[0] is not None
            assert results[0].read_bytes() == exported[track.artwork_path]
        finally:
            link.close()
            worker.join(3)
