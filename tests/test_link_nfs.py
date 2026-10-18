import hashlib
import time
from threading import Event

import pytest
from link_peer import Peer

from pi_dvs.link.nfs import Client, NfsError, Reader
from pi_dvs.rekordbox.records import ImportCancelled, ImportFailure


def test_lost_duplicate_malformed_and_wrong_peer_packets(tmp_path):
    with Peer(fault="drop") as peer, Client("127.0.0.1", timeout=0.04, interval=0) as client:
        client.mount("127.0.0.1", peer.port)
        target = tmp_path / "audio.mp3"
        result = client.download("/Contents/Élise/東京.mp3", target)
        assert target.read_bytes() == peer.data
        assert result.sha256 == hashlib.sha256(peer.data).hexdigest()
        assert result.retries == 1
        assert peer.reads[0][0] == peer.reads[1][0]
        assert "東京.mp3" in peer.lookups
        assert list(tmp_path.iterdir()) == [target]


def test_legacy_sparse_attributes_and_missing_file_recovery(tmp_path):
    with Peer(sparse=True) as peer, Client("127.0.0.1", interval=0) as client:
        client.mount("127.0.0.1", peer.port)
        with pytest.raises(NfsError) as failure:
            client.download("/absent", tmp_path / "missing")
        assert failure.value.status == 70
        assert not list(tmp_path.iterdir())
        target = tmp_path / "recovered.mp3"
        client.download("/song", target)
        assert target.read_bytes() == peer.data
        with pytest.raises(FileExistsError):
            client.download("/song", target)
        assert target.read_bytes() == peer.data


def test_timeout_is_bounded_and_never_publishes_partial(tmp_path):
    with Peer(fault="timeout") as peer, Client("127.0.0.1", timeout=0.02, interval=0) as client:
        client.mount("127.0.0.1", peer.port)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            client.download("/song", tmp_path / "audio")
        assert time.monotonic() - started < 0.5
        assert len(peer.reads) == 3
        assert len({xid for xid, _, _ in peer.reads}) == 1
        assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("fault", ["changed", "empty", "checksum", "cancel", "identity"])
def test_failed_downloads_leave_no_cache_file(tmp_path, fault):
    cancelled = Event()
    with Peer(fault=fault) as peer, Client("127.0.0.1", cancelled=cancelled, interval=0) as client:
        client.mount("127.0.0.1", peer.port)
        if fault == "cancel":
            peer.cancel = cancelled
        options = {"expected_sha256": "bad"} if fault == "checksum" else {}
        if fault == "identity":
            options = {"expected_identity": (999,)}
        with pytest.raises((ImportFailure, ImportCancelled)):
            client.download("/song", tmp_path / "audio", **options)
        assert not list(tmp_path.iterdir())


def test_pacing_size_limits_and_paths(tmp_path):
    with Peer() as peer, Client("127.0.0.1", interval=0.01) as client:
        client.mount("127.0.0.1", peer.port)
        with pytest.raises(ImportFailure, match="excessive"):
            client.download("/song", tmp_path / "audio", max_bytes=1)
        assert not peer.reads
        for path in ["", "/", "../secret", "/a/../b", "a\\b", "a\0b"]:
            with pytest.raises(ImportFailure):
                client.download(path, tmp_path / "audio")
        started = time.monotonic()
        client.download("/song", tmp_path / "audio")
        assert time.monotonic() - started >= 0.05
    with pytest.raises(ImportFailure):
        Reader(b"").integer()
    with pytest.raises(ImportFailure):
        Reader(b"\0\0\0\x10").opaque(2)
    with pytest.raises(ValueError):
        Client("127.0.0.1", attempts=0)


def test_cancellation_interrupts_a_silent_receive(tmp_path):
    from threading import Timer

    event = Event()
    with Peer(fault="timeout") as peer, Client("127.0.0.1", cancelled=event) as client:
        client.mount("127.0.0.1", peer.port)
        timer = Timer(0.03, event.set)
        timer.start()
        started = time.monotonic()
        try:
            with pytest.raises(ImportCancelled):
                client.download("/song", tmp_path / "audio")
            assert time.monotonic() - started < 0.4
            assert len(peer.reads) == 1
            assert not list(tmp_path.iterdir())
        finally:
            timer.cancel()


def test_final_lookup_and_destination_creation_races_do_not_publish(tmp_path):
    for race in ("changed", "created"):
        target = tmp_path / race
        with Peer(sparse=True) as peer, Client("127.0.0.1", interval=0) as client:
            client.mount("127.0.0.1", peer.port)

            def change(_, race=race, target=target):
                if race == "changed":
                    peer.data += b"replacement"
                else:
                    target.write_bytes(b"owned by another writer")

            peer.read_hook = change
            with pytest.raises(ImportFailure if race == "changed" else FileExistsError):
                client.download("/song", target)
            assert not list(tmp_path.glob(".partial-*"))
            if race == "created":
                assert target.read_bytes() == b"owned by another writer"
            else:
                assert not target.exists()


def test_pacing_clock_crossing_never_sleeps_negative(monkeypatch):
    from types import SimpleNamespace

    ticks = iter(i * 0.4 for i in range(100))
    sleeps = []

    def sleep(seconds):
        assert seconds >= 0
        sleeps.append(seconds)

    with Peer() as peer, Client("127.0.0.1", timeout=10) as client:
        client.next_send = 1
        monkeypatch.setattr(
            "pi_dvs.link.nfs.time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=sleep)
        )
        assert client.rpc(("127.0.0.1", peer.port), 100000, 2, 3, b"")
        assert sleeps == [0.0]


def test_whole_transfer_deadline_cannot_be_reset_by_slow_successes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    current = [0.0]
    with Peer(data=b"x" * 50000) as peer, Client("127.0.0.1", interval=0) as client:
        client.mount("127.0.0.1", peer.port)
        original = client.nfs

        def delayed(procedure, payload):
            result = original(procedure, payload)
            if procedure == 6:
                current[0] += 2
            return result

        monkeypatch.setattr(
            "pi_dvs.link.nfs.time",
            SimpleNamespace(monotonic=lambda: current[0], sleep=lambda _: None),
        )
        client.next_send = 0
        monkeypatch.setattr(client, "nfs", delayed)
        with pytest.raises(TimeoutError, match="deadline"):
            client.download("/song", tmp_path / "audio")
        assert len(peer.reads) < 10
        assert not list(tmp_path.iterdir())
