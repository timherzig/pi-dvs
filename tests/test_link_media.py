import hashlib
from dataclasses import replace
from threading import Event

import pytest

from pi_dvs.library import Library, demo_library
from pi_dvs.link.media import AudioCache, Cancel, Sources, relabel
from pi_dvs.link.nfs import Download
from pi_dvs.model import Track
from pi_dvs.rekordbox.records import ImportCancelled, ImportFailure


def test_reconnect_never_reuses_ids_or_accepts_old_imports():
    sources = Sources()
    first = sources.observe("cdj:one", "CDJ 1", "same")
    fixture = Library(tuple(replace(t, export_id=t.id) for t in demo_library().tracks))
    original = relabel(fixture, first)
    sources.publish(first, original)
    second = sources.observe("cdj:two", "CDJ 2", "other")
    sources.disconnect(first.key)
    replacement = sources.observe(first.key, first.name, "same")
    assert replacement.source_id != first.source_id
    assert first.cancelled.is_set()
    assert not second.cancelled.is_set()
    assert sources.media(first.source_id) is first
    with pytest.raises(ImportCancelled):
        sources.publish(first, original)
    library = relabel(fixture, replacement)
    sources.publish(replacement, library)
    assert sources.view(first.key).library is library
    assert library.tracks[0].id != original.tracks[0].id
    sources.fail(replacement, "try again")
    assert sources.view(first.key).error == "try again"
    sources.close()
    assert all(v.media.cancelled.is_set() for v in sources.views())


def test_cache_evicts_unpinned_files_but_protects_both_decks_and_queued_loads(tmp_path):
    cache = AudioCache(tmp_path, limit=12)
    tracks = [Track(str(i), "Track", "Artist", 1, relative_path=f"{i}.mp3") for i in range(4)]
    cancelled = Cancel(Event())
    calls = []

    def fetch(path):
        calls.append(path)
        path.write_bytes(b"abcdef")
        return Download(6, hashlib.sha256(b"abcdef").hexdigest(), (), 0)

    a = cache.materialize(tracks[0], 6, fetch, cancelled)
    b = cache.materialize(tracks[1], 6, fetch, cancelled)
    cache.protect(tuple(tracks))
    assert cache.materialize(tracks[0], 6, fetch, cancelled) == a
    assert len(calls) == 2
    with pytest.raises(ImportFailure, match="full"):
        cache.materialize(tracks[2], 6, fetch, cancelled)
    assert a.exists() and b.exists()
    cache.protect((tracks[0], tracks[2]))
    c = cache.materialize(tracks[2], 6, fetch, cancelled)
    assert a.exists() and c.exists() and not b.exists()
    a.write_bytes(b"broken")
    with pytest.raises(ImportFailure, match="changed"):
        cache.materialize(tracks[0], 6, fetch, cancelled)
    with pytest.raises(ImportFailure, match="capacity"):
        cache.materialize(tracks[3], 100, fetch, cancelled)


def test_cancel_at_publication_and_wrong_size_are_never_reused(tmp_path):
    cache = AudioCache(tmp_path)
    event = Event()
    track = Track("id", "T", "A", 1, relative_path="audio.wav")

    def fetch(path):
        path.write_bytes(b"abc")
        event.set()
        return Download(3, "x", (), 0)

    with pytest.raises(ImportCancelled):
        cache.materialize(track, 3, fetch, Cancel(event))
    assert not list(tmp_path.iterdir())
    event.clear()

    def wrong(path):
        path.write_bytes(b"abc")
        return Download(3, "x", (), 0)

    with pytest.raises(ImportFailure, match="size changed"):
        cache.materialize(track, 4, wrong, Cancel(event))
    assert not list(tmp_path.iterdir())


def test_recovered_xwax_track_pins_its_actual_cached_path(tmp_path):
    cache = AudioCache(tmp_path, limit=6)
    original = Track("first", "T", "A", 1, relative_path="x.mp3")

    def fetch(path):
        path.write_bytes(b"abcdef")
        return Download(6, hashlib.sha256(b"abcdef").hexdigest(), (), 0)

    path = cache.materialize(original, 6, fetch, Cancel(Event()))
    recovered = Track("xwax:" + str(path), "Recovered", "xwax", 1, audio_path=path)
    cache.protect((recovered,))
    with pytest.raises(ImportFailure, match="full"):
        cache.materialize(replace(original, id="next"), 6, fetch, Cancel(Event()))
    assert path.read_bytes() == b"abcdef"


def test_cache_owner_blocks_other_instances_until_all_workers_exit(tmp_path):
    from pi_dvs.link.media import CacheLease

    owner, other = CacheLease(tmp_path), CacheLease(tmp_path)
    with owner.use():
        with owner.use():
            owner.close()
            with pytest.raises(ImportFailure, match="another pi-dvs"):
                with other.use():
                    pytest.fail("Another instance entered an active cache")
        with pytest.raises(ImportFailure):
            with other.use():
                pytest.fail("Cache released before outer worker exited")
    with other.use():
        assert (tmp_path / "owner.lock").exists()
    with pytest.raises(ImportCancelled):
        with owner.use():
            pytest.fail("Closed owner restarted")
    other.close()


def test_exclusive_cache_owner_removes_only_abandoned_partial_audio(tmp_path):
    from pi_dvs.link.media import CacheLease

    audio = tmp_path / "audio"
    audio.mkdir()
    partial = audio / ".partial-crashed"
    partial.write_bytes(b"incomplete")
    complete = audio / ".audio-loaded.mp3"
    complete.write_bytes(b"complete")
    owner = CacheLease(tmp_path)
    with owner.use():
        assert not partial.exists()
        assert complete.read_bytes() == b"complete"
        active = audio / ".partial-active"
        active.write_bytes(b"in progress")
        with owner.use():
            assert active.exists()  # only first acquisition cleans up
    owner.close()
