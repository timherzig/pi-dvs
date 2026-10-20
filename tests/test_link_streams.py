"""Producer ownership outlives early readiness and follows confirmed deck pins."""

import io
import time
from dataclasses import replace
from threading import Event, Thread

from test_stream_audio import aiff

from pi_dvs.link.media import CacheLease
from pi_dvs.link.nfs import FileInfo
from pi_dvs.link.streams import Streams
from pi_dvs.model import Track
from pi_dvs.rekordbox.records import ImportCancelled
from pi_dvs.stream_audio import import_stream


def until(condition):
    deadline = time.monotonic() + 3
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert condition()


def test_early_result_keeps_producer_owned_until_confirmed_retirement(tmp_path):
    data, pcm = aiff(frames=44100 * 12)
    lease = CacheLease(tmp_path)
    streams = Streams(tmp_path / "audio" / ".streams", lease)
    track = Track("remote", "AIFF", "", 12)
    streams.protect((), preparing=(track.id,), authoritative=True)
    release = Event()
    source = tmp_path / "source"
    attributes = [0] * 17
    attributes[5] = len(data)
    info = FileInfo(bytes(32), tuple(attributes))

    def fetch(cancelled, progress):
        with lease.use(), source.open("wb") as output:
            initial = len(data) - len(pcm) + 44100 * 10 * 4
            output.write(data[:initial])
            output.flush()
            progress(source, info, initial)
            while not release.wait(0.01):
                if cancelled.is_set():
                    raise ImportCancelled()
            output.write(data[initial:])
            output.flush()
            progress(source, info, len(data))
        return source

    try:
        prepared = streams.prepare(track, Event(), fetch)
        assert prepared.streaming and prepared.duration == 12
        assert streams.state(track).status == "loading"
        attached = replace(track, audio_path=prepared.path, streaming=True)
        # A rejected replacement still reports the old engine path as owned.
        streams.protect((attached,), authoritative=True)
        session = streams.sessions[track.id]
        assert not session.cancelled.wait(0.1)
        output = io.BytesIO()
        importer = Thread(target=import_stream, args=(prepared.path, output), daemon=True)
        importer.start()
        until(lambda: len(output.getvalue()) >= 44100 * 10 * 4)
        assert importer.is_alive()
        release.set()
        importer.join(2)
        assert not importer.is_alive()
        assert len(output.getvalue()) == len(pcm)
        assert streams.state(track).status == "complete"
        streams.protect((attached,), authoritative=False)
        time.sleep(0.1)
        assert prepared.path.exists()  # Disconnected GUI cannot assume native release.
        streams.protect((), authoritative=True)
        until(lambda: not prepared.path.exists())
    finally:
        release.set()
        streams.close()
        lease.close()


def test_terminal_publication_retains_lease_and_never_blocks_gui_snapshots(tmp_path, monkeypatch):
    import pytest

    import pi_dvs.link.streams as module
    from pi_dvs.rekordbox.records import ImportFailure

    data, _ = aiff(frames=4410)
    lease = CacheLease(tmp_path)
    streams = Streams(tmp_path / "audio" / ".streams", lease)
    track = Track("short", "Short", "", 0.1)
    streams.protect((), preparing=(track.id,), authoritative=True)
    entered, release = Event(), Event()
    original = module.write_state

    def blocked(directory, available, state, error=""):
        if state == "complete":
            entered.set()
            assert release.wait(3)
        original(directory, available, state, error)

    monkeypatch.setattr(module, "write_state", blocked)
    attributes = [0] * 17
    attributes[5] = len(data)

    def fetch(cancelled, progress):
        source = tmp_path / "source"
        source.write_bytes(data)
        progress(source, FileInfo(bytes(32), tuple(attributes)), len(data))
        return source

    other = CacheLease(tmp_path)
    try:
        streams.prepare(track, Event(), fetch)
        assert entered.wait(1)
        started = time.monotonic()
        assert streams.state(track).status == "loading"
        streams.protect((), preparing=(track.id,), authoritative=False)
        streams.close()
        lease.close()
        assert time.monotonic() - started < 0.1
        with pytest.raises(ImportFailure):
            with other.use():
                pytest.fail("Producer released ownership before terminal publication")
        release.set()
        until(lambda: streams.sessions[track.id].finished.is_set())
        streams._janitor.join(1)
        streams.sessions[track.id].thread.join(1)
        with other.use():
            pass
    finally:
        release.set()
        streams.close()
        lease.close()
        other.close()


def test_blocked_retirement_does_not_block_gui_and_missing_deck_does_not_keep_producers(
    tmp_path, monkeypatch
):
    import pi_dvs.link.streams as module

    lease = CacheLease(tmp_path)
    streams = Streams(tmp_path / "audio" / ".streams", lease)
    track = Track("queued", "Queued", "", 1)
    entered, release = Event(), Event()
    original = module.shutil.rmtree

    def blocked(path, **kwargs):
        entered.set()
        assert release.wait(3)
        original(path, **kwargs)

    monkeypatch.setattr(module.shutil, "rmtree", blocked)
    job_started = Event()

    def fetch(cancelled, progress):
        job_started.set()
        assert cancelled.wait(3)
        raise ImportCancelled()

    errors = []
    wait_cancelled = Event()

    def prepare():
        try:
            streams.prepare(track, wait_cancelled, fetch)
        except (ValueError, ImportCancelled) as error:
            errors.append(error)

    waiter = Thread(target=prepare, daemon=True)
    streams.protect((), preparing=(track.id,), authoritative=False)
    waiter.start()
    try:
        assert job_started.wait(1)
        session = streams.sessions[track.id]
        # The awaiting GUI job is cancelled; another deck is still missing.
        wait_cancelled.set()
        waiter.join(1)
        assert not waiter.is_alive()
        streams.protect((), authoritative=False)
        until(session.cancelled.is_set)
        waiter.join(1)
        assert errors
        # Known current-process sessions retire despite unknown orphan ownership.
        assert entered.wait(1)
        started = time.monotonic()
        streams.protect((), authoritative=False)
        assert streams.state(track) is None
        streams.close()
        assert time.monotonic() - started < 0.1
    finally:
        release.set()
        streams.close()
        lease.close()


def test_busy_cache_is_a_terminal_error_instead_of_an_unfinished_wait(tmp_path):
    import pytest

    from pi_dvs.rekordbox.records import ImportFailure

    owner, contender = CacheLease(tmp_path), CacheLease(tmp_path)
    streams = Streams(tmp_path / "audio" / ".streams", contender)
    track = Track("track", "Track", "", 1)
    try:
        with owner.use():
            started = time.monotonic()
            with pytest.raises(ImportFailure, match="another pi-dvs"):
                streams.prepare(track, Event(), lambda *_: pytest.fail("Unexpected transfer"))
            assert time.monotonic() - started < 0.5
            assert streams.sessions[track.id].finished.is_set()
    finally:
        streams.close()
        owner.close()
        contender.close()


def test_rejected_retry_does_not_stay_pinned_by_old_descriptor_with_same_track_id(tmp_path):
    data, pcm = aiff(frames=44100 * 12)
    lease = CacheLease(tmp_path)
    streams = Streams(tmp_path / "audio" / ".streams", lease)
    track = Track("same", "Same track", "", 12)
    failure = Event()
    attributes = [0] * 17
    attributes[5] = len(data)
    attempts = []

    def fetch(cancelled, progress):
        source = tmp_path / f"attempt-{len(attempts)}"
        attempts.append(source)
        prefix = len(data) - len(pcm) + 44100 * 10 * 4
        source.write_bytes(data[:prefix])
        progress(source, FileInfo(bytes(32), tuple(attributes)), prefix)
        while not cancelled.wait(0.01):
            if len(attempts) == 1 and failure.is_set():
                raise ImportCancelled()
        raise ImportCancelled()

    try:
        streams.protect((), preparing=(track.id,), authoritative=True)
        first = streams.prepare(track, Event(), fetch)
        old = replace(track, audio_path=first.path, streaming=True)
        streams.protect((old,), authoritative=True)
        old_session = streams.sessions[track.id]
        failure.set()
        until(old_session.finished.is_set)
        streams.protect((old,), preparing=(track.id,), authoritative=True)
        second = streams.prepare(track, Event(), fetch)
        new = replace(track, audio_path=second.path, streaming=True)
        assert first.path != second.path
        streams.protect((old, new), authoritative=True)
        retry = streams.sessions[track.id]
        assert not retry.cancelled.wait(0.1)
        streams.protect((old,), authoritative=True)  # Native rejected the new handoff.
        until(retry.cancelled.is_set)
        until(lambda: not second.path.exists())
        assert first.path.exists()
    finally:
        streams.close()
        lease.close()


def test_completed_fallback_reenters_serialized_cache_instead_of_returning_evicting_path(tmp_path):
    from threading import Lock

    lease = CacheLease(tmp_path)
    streams = Streams(tmp_path / "audio" / ".streams", lease)
    track = Track("fallback", "Unsupported AIFF", "", 1)
    source = tmp_path / "cached.aiff"
    source.write_bytes(b"complete file")
    queue = Lock()
    entered = Event()
    results = []

    def fetch(cancelled, progress):
        entered.set()
        with queue:
            source.write_bytes(b"verified again")
            return source

    try:
        streams.protect((), preparing=(track.id,), authoritative=True)
        first = streams.prepare(track, Event(), fetch)
        assert not first.streaming
        until(lambda: streams.sessions[track.id].finished.is_set())
        entered.clear()
        with queue:  # Another serialized transfer has claimed this file for eviction.
            worker = Thread(target=lambda: results.append(streams.prepare(track, Event(), fetch)))
            worker.start()
            assert entered.wait(1)
            assert not results
            source.unlink()
        worker.join(2)
        assert results[0].path.read_bytes() == b"verified again"
    finally:
        streams.close()
        lease.close()
