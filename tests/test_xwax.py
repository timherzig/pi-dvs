"""Contract tests run on Mac/Linux using actual Unix streams, never audio hardware."""

import socket
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep

import pytest

from pi_dvs.model import Status, Track
from pi_dvs.xwax import XwaxEngine
from pi_dvs.xwax.protocol import Connection, ProtocolError, command_line, parse_status


class Server:
    def __init__(self, path):
        self.path = path
        self.stop = Event()
        self.log = []
        self.state = parse_status("DVS2 STATE - NONE EMPTY 0 1 1 0 0 0 0 ")
        self.auto = True
        self.ack = "ACCEPTED"
        self.fragment = False
        self.hang = False
        self.drop_command = False
        self.override = None
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        self.sock.listen()
        self.sock.settimeout(0.05)
        self.client = None
        self.thread = Thread(target=self.run, daemon=True)
        self.thread.start()

    def status(self):
        s = self.state
        return (
            f"DVS2 STATE {s.request_id} {s.result} {s.state} {int(s.active)} "
            f"{int(s.protected)} {int(s.timecode_control)} {int(s.position_known)} "
            f"{s.elapsed} {s.duration} {s.pitch} {s.path}\n"
        ).encode()

    def run(self):
        while not self.stop.is_set():
            try:
                client, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.client = client
            with client:
                client.settimeout(0.05)
                buffer = b""
                while not self.stop.is_set():
                    try:
                        data = client.recv(4096)
                        if not data:
                            break
                        buffer += data
                        while b"\n" in buffer:
                            raw, buffer = buffer.split(b"\n", 1)
                            line = raw.decode()
                            self.log.append(line)
                            if line == "DVS2 STATUS":
                                if self.hang:
                                    continue
                                response = (
                                    self.override if self.override is not None else self.status()
                                )
                            else:
                                _, verb, request, *tail = line.split(" ", 3)
                                if self.drop_command:
                                    client.shutdown(socket.SHUT_RDWR)
                                    break
                                response = f"DVS2 ACK {request} {self.ack}\n".encode()
                                if self.ack == "ACCEPTED":
                                    self.state = replace(
                                        self.state, request_id=request, result="PENDING"
                                    )
                                    if self.auto:
                                        self.state = replace(
                                            self.state,
                                            result="OK",
                                            state="EMPTY" if verb == "UNLOAD" else "READY",
                                            path="" if verb == "UNLOAD" else tail[0],
                                            duration=100,
                                        )
                            if self.fragment:
                                for part in (response[:7], response[7:15], response[15:]):
                                    client.sendall(part)
                                    sleep(0.002)
                            else:
                                client.sendall(response)
                    except TimeoutError:
                        continue
                    except OSError:
                        break
            self.client = None

    def disconnect(self):
        if self.client:
            try:
                self.client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self):
        self.stop.set()
        self.disconnect()
        self.sock.close()
        self.thread.join(1)
        self.path.unlink(missing_ok=True)


@pytest.fixture
def pair():
    with TemporaryDirectory(prefix="dvs-", dir="/tmp") as directory:
        servers = [Server(Path(directory) / letter) for letter in ("a", "b")]
        engine = XwaxEngine(
            tuple(s.path for s in servers), poll=0.01, timeout=0.1, load_timeout=0.3
        )
        wait_for(lambda: all(d.can_change_track for d in engine.decks))
        yield engine, servers
        engine.close()
        for worker in engine._connections:
            worker.thread.join(1)
        for server in servers:
            server.close()


def wait_for(condition, timeout=3):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if condition():
            return
        sleep(0.005)
    assert condition()


def audio(path="/music/Café 東京 with spaces.wav"):
    return Track("real", "Café", "Artist", 60, audio_path=Path(path))


def mutations(server):
    return [line for line in server.log if line != "DVS2 STATUS"]


def test_two_decks_fragmented_status_spaces_and_confirmed_unload(pair):
    engine, (a, b) = pair
    a.fragment = True
    engine.load(0, audio())
    wait_for(lambda: engine.decks[0].status == Status.READY)
    assert engine.decks[0].track.title == "Café"
    assert engine.decks[0].track.duration == 100
    assert engine.decks[0].track.audio_path == audio().audio_path
    assert engine.decks[1].status == Status.EMPTY
    assert not mutations(b)
    engine.load(1, audio("/music/b.wav"))
    wait_for(lambda: engine.decks[1].status == Status.READY)
    engine.unload(0)
    wait_for(lambda: engine.decks[0].status == Status.EMPTY)
    assert engine.decks[1].status == Status.READY
    assert engine.advance(0)
    assert not engine.advance(0)


def test_acceptance_is_not_import_confirmation_and_same_path_needs_new_result(pair):
    engine, (a, _) = pair
    engine.load(0, audio())
    wait_for(lambda: engine.decks[0].status == Status.READY)
    a.auto = False
    previous_id = a.state.request_id
    engine.load(0, audio())
    wait_for(lambda: a.state.request_id != previous_id)
    assert engine.decks[0].status == Status.WAITING
    assert not engine.decks[0].can_change_track
    a.state = replace(a.state, state="IMPORTING")
    wait_for(lambda: engine.decks[0].status == Status.LOADING)
    a.state = replace(a.state, state="READY", result="OK")
    wait_for(lambda: engine.decks[0].status == Status.READY)
    assert engine.decks[0].can_change_track


def test_failed_decode_is_confirmed_and_recovers(pair):
    engine, (a, _) = pair
    a.auto = False
    engine.load(0, audio())
    wait_for(lambda: bool(mutations(a)))
    a.state = replace(a.state, path=str(audio().audio_path), state="ERROR", result="ERROR")
    wait_for(lambda: engine.decks[0].status == Status.ERROR)
    assert "decode" in engine.decks[0].error or "load" in engine.decks[0].error
    a.auto = True
    engine.load(0, audio())
    wait_for(lambda: engine.decks[0].status == Status.READY)
    assert not engine.decks[0].error


@pytest.mark.parametrize("ack", ["LOCKED", "BUSY", "UNPROTECTED", "INVALID", "ERROR"])
def test_rejection_preserves_confirmed_deck_and_allows_retry(pair, ack):
    engine, (a, _) = pair
    a.ack = ack
    engine.load(0, audio())
    wait_for(lambda: bool(engine.decks[0].error))
    assert engine.decks[0].track is None
    assert engine.decks[0].status == Status.EMPTY
    a.ack = "ACCEPTED"
    engine.load(0, audio())
    wait_for(lambda: engine.decks[0].status == Status.READY)


def test_reconnect_adopts_playing_external_track_without_commands(pair):
    engine, (a, _) = pair
    a.state = replace(
        a.state,
        state="READY",
        path="/external/playing.wav",
        duration=240,
        elapsed=42.5,
        active=True,
        pitch=-0.5,
        timecode_control=False,
    )
    a.disconnect()
    wait_for(lambda: engine.decks[0].status == Status.PLAYING)
    assert engine.decks[0].position == 42.5
    assert engine.decks[0].track.audio_path == Path("/external/playing.wav")
    assert "Internal playback" in engine.decks[0].transport_message
    assert not engine.decks[0].can_change_track
    with pytest.raises(ValueError):
        engine.unload(0)
    assert not mutations(a)


def test_restart_discards_uncertain_load_and_never_replays(pair):
    engine, servers = pair
    a = servers[0]
    a.drop_command = True
    engine.load(0, audio())
    wait_for(lambda: len(mutations(a)) == 1)
    a.close()
    wait_for(lambda: engine.decks[0].status == Status.DISCONNECTED)
    servers[0] = Server(a.path)
    wait_for(lambda: engine.decks[0].status == Status.EMPTY)
    sleep(0.1)
    assert not mutations(servers[0])
    assert engine.decks[0].track is None


def test_status_timeout_does_not_block_other_deck_or_caller(pair):
    engine, (a, _) = pair
    a.hang = True
    wait_for(lambda: engine.decks[0].status == Status.DISCONNECTED)
    start = monotonic()
    engine.load(1, audio())
    assert monotonic() - start < 0.05
    wait_for(lambda: engine.decks[1].status == Status.READY)
    assert not engine.decks[0].can_change_track
    a.hang = False
    wait_for(lambda: engine.decks[0].status == Status.EMPTY)


def test_confirmation_timeout_discards_request_without_replay(pair):
    engine, (a, _) = pair
    a.auto = False
    engine.load(0, audio())
    wait_for(lambda: engine.decks[0].status == Status.DISCONNECTED)
    wait_for(lambda: engine.decks[0].status == Status.WAITING)
    assert not engine.decks[0].can_change_track
    assert len(mutations(a)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"active": True, "pitch": 1},
        {"active": True, "pitch": -1},
        {"protected": False},
        {"state": "IMPORTING", "path": "/a.wav"},
    ],
)
def test_motion_import_and_missing_protection_disable_mutations(pair, changes):
    engine, (a, _) = pair
    a.state = replace(a.state, **changes)
    wait_for(lambda: not engine.decks[0].can_change_track)
    with pytest.raises(ValueError):
        engine.load(0, audio())
    with pytest.raises(ValueError):
        engine.unload(0)
    assert not mutations(a)


def test_motion_without_position_is_explicit_and_not_a_needle_sensor(pair):
    engine, (a, _) = pair
    a.state = replace(a.state, active=True, state="READY", path="/a.wav", pitch=1)
    wait_for(lambda: engine.decks[0].status == Status.PLAYING)
    assert "Absolute position unavailable" in engine.decks[0].transport_message
    assert not engine.decks[0].needle_down


@pytest.mark.parametrize(
    "path", ["relative.wav", "/bad\nLOAD /x", "/bad\rname", "/bad\0name", "/" + "é" * 600]
)
def test_invalid_paths_never_reach_socket(pair, path):
    engine, (a, _) = pair
    with pytest.raises(ValueError):
        engine.load(0, audio(path))
    assert not mutations(a)


def test_invalid_decks_demo_tracks_configuration_and_close(pair):
    engine, _ = pair
    for index in (-1, 2):
        with pytest.raises(ValueError):
            engine.load(index, audio())
    with pytest.raises(ValueError):
        engine.load(0, Track("demo", "Demo", "", 60))
    with pytest.raises(ValueError):
        XwaxEngine((Path("/a"), Path("/a")))
    for interval in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            XwaxEngine((Path("/a"), Path("/b")), timeout=interval)
    engine.close()
    with pytest.raises(ValueError):
        engine.load(0, audio())


def test_missing_engine_is_explicit():
    with TemporaryDirectory(dir="/tmp") as directory:
        engine = XwaxEngine((Path(directory) / "a", Path(directory) / "b"))
        try:
            wait_for(lambda: all(d.error for d in engine.decks))
            assert all(d.status == Status.MISSING and not d.can_change_track for d in engine.decks)
        finally:
            engine.close()


@pytest.mark.parametrize(
    "line",
    [
        "STATUS EMPTY 0 0",
        "DVS2 STATE invalid NONE EMPTY 0 1 0 0 0 0 0 ",
        "DVS2 STATE - WHAT EMPTY 0 1 0 0 0 0 0 ",
        "DVS2 STATE - NONE EMPTY 2 1 0 0 0 0 0 ",
        "DVS2 STATE - NONE EMPTY 0 1 0 0 nan 0 0 ",
        "DVS2 STATE - NONE EMPTY 0 1 0 0 word 0 0 ",
        "DVS2 STATE - NONE EMPTY 0 1 0 0 0 -1 0 ",
        "DVS2 STATE - NONE EMPTY 0 1 0 0 0 0 0 /a.wav",
        "DVS2 STATE - NONE READY 0 1 0 0 0 0 0 relative.wav",
        "DVS2 STATE - NONE READY 0 1 0 0 0 0 0 /bad\0path",
    ],
)
def test_parser_rejects_incompatible_and_malformed_state(line):
    with pytest.raises(ProtocolError):
        parse_status(line)


def test_incompatible_engine_does_not_accept_commands(pair):
    engine, (a, _) = pair
    a.override = b"STATUS EMPTY 0 0\n"
    wait_for(lambda: engine.decks[0].status == Status.ERROR)
    assert "DVS2" in engine.decks[0].error
    assert not engine.decks[0].can_change_track


def test_connection_preserves_coalesced_lines_and_rejects_invalid_utf8_and_oversize():
    left, right = socket.socketpair()
    with left, right:
        connection = Connection(left, 0.1)
        right.sendall(b"first\nsecond\n")
        assert connection.exchange(b"STATUS\n") == "first"
        assert connection.exchange(b"STATUS\n") == "second"
        right.sendall(b"\xff\n")
        with pytest.raises(ProtocolError, match="UTF-8"):
            connection.exchange(b"STATUS\n")
    left, right = socket.socketpair()
    with left, right:
        sender = Thread(target=right.sendall, args=(b"x" * 9000,), daemon=True)
        sender.start()
        with pytest.raises(ProtocolError, match="limit"):
            Connection(left, 0.1).exchange(b"STATUS\n")
        sender.join(1)


def test_utf8_command_encoding_rejects_surrogates():
    with pytest.raises(ValueError, match="UTF-8"):
        command_line("a" * 32, Path("/bad\udcff.wav"))


def test_prepared_load_from_old_connection_cannot_cross_reconnect(pair):
    engine, (a, _) = pair
    generation = engine.decks[0].connection_generation
    a.disconnect()
    wait_for(lambda: engine.decks[0].connection_generation != generation)
    with pytest.raises(ValueError, match="reconnected"):
        engine.load(0, audio(), generation=generation)
    assert not mutations(a)


def test_rejection_when_motion_starts_before_dispatch(pair):
    engine, (a, _) = pair
    # Hold only the adapter's state lock while arranging a motor start, so its
    # next fresh STATUS must supersede the previous stopped snapshot.
    connection = engine._connections[0]
    with connection.lock:
        a.state = replace(a.state, active=True, pitch=1)
    try:
        engine.load(0, audio())
    except ValueError:
        pass  # The newer snapshot may already have disabled loading.
    wait_for(lambda: not engine.decks[0].can_change_track)
    sleep(0.05)
    assert not mutations(a)


def test_unknown_acknowledgement_and_wrong_request_are_incompatible(pair):
    engine, (a, _) = pair
    a.ack = "OTHER"
    engine.load(0, audio())
    wait_for(lambda: engine.decks[0].status == Status.ERROR)
    assert "acknowledgement" in engine.decks[0].error
    left, right = socket.socketpair()
    with left, right:
        right.sendall(b"DVS2 ACK wrong ACCEPTED\n")
        with pytest.raises(ProtocolError, match="this request"):
            Connection(left, 0.1).command("a" * 32, b"DVS2 UNLOAD abc\n")


def test_worker_rejection_preserves_old_track_after_acceptance(pair):
    engine, (a, _) = pair
    engine.load(0, audio())
    wait_for(lambda: engine.decks[0].status == Status.READY)
    a.auto = False
    previous_id = a.state.request_id
    engine.load(0, audio("/different.wav"))
    wait_for(lambda: a.state.request_id != previous_id)
    a.state = replace(a.state, result="LOCKED")
    wait_for(lambda: engine.decks[0].can_change_track)
    assert engine.decks[0].track.audio_path == audio().audio_path
    assert "Stop the record" in engine.decks[0].error


def test_successful_result_must_match_requested_file(pair):
    engine, (a, _) = pair
    a.auto = False
    engine.load(0, audio())
    wait_for(lambda: bool(mutations(a)))
    a.state = replace(a.state, result="OK", state="READY", path="/wrong.wav")
    wait_for(lambda: engine.decks[0].status == Status.ERROR)
    assert "requested track" in engine.decks[0].error


def test_stopped_audio_callbacks_disable_changes_and_recover(pair):
    engine, (a, _) = pair
    a.override = b"DVS2 STALE\n"
    wait_for(lambda: engine.decks[0].status == Status.ERROR)
    assert "audio callbacks stopped" in engine.decks[0].error
    assert not engine.decks[0].can_change_track
    a.override = None
    wait_for(lambda: engine.decks[0].status == Status.EMPTY)
    assert engine.decks[0].can_change_track
    assert not mutations(a)


def test_progressive_status_keeps_total_duration_and_confirms_before_complete(pair):
    engine, (a, _) = pair
    a.auto = False
    track = replace(audio(), duration=120, streaming=True)
    engine.load(0, track)
    wait_for(lambda: a.state.result == "PENDING")
    request = a.state.request_id
    a.override = (
        f"DVS2 STREAM_STATE {request} OK STREAMING 0 1 1 0 0 120 0 10 {track.audio_path}\n"
    ).encode()
    wait_for(lambda: engine.decks[0].status == Status.READY)
    assert engine.decks[0].track.duration == 120
    assert engine.decks[0].buffered_duration == 10
    assert not engine.decks[0].download_complete
    assert engine.decks[0].can_change_track
    # No command timeout while a confirmed progressive import is still growing.
    sleep(0.4)
    assert engine.decks[0].status == Status.READY
    a.override = (
        f"DVS2 STREAM_STATE {request} OK STREAMING 1 1 1 1 20 120 1 10 {track.audio_path}\n"
    ).encode()
    wait_for(lambda: engine.decks[0].status == Status.BUFFERING)
    assert not engine.decks[0].can_change_track
    a.override = (
        f"DVS2 STREAM_STATE {request} OK STREAMING 1 1 1 1 20 120 1 30 {track.audio_path}\n"
    ).encode()
    wait_for(lambda: engine.decks[0].status == Status.PLAYING)
    a.override = (
        f"DVS2 STREAM_STATE {request} OK READY 0 1 1 1 20 120 0 120 {track.audio_path}\n"
    ).encode()
    wait_for(lambda: engine.decks[0].download_complete)
    assert engine.decks[0].buffered_duration == 120


@pytest.mark.parametrize("extent", ["nan", "inf", "-1", "invalid"])
def test_progressive_telemetry_rejects_invalid_extent(extent):
    with pytest.raises(ProtocolError):
        parse_status(f"DVS2 STREAM_STATE - NONE STREAMING 0 1 1 0 0 120 0 {extent} /stream")
