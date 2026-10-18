"""Optional, nonblocking two-deck connection to the patched upstream xwax build."""

import math
import socket
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from pi_dvs.model import DeckState, Status, Track
from pi_dvs.xwax.protocol import CommandRejected, Connection, ProtocolError, Snapshot, command_line


@dataclass(frozen=True)
class Request:
    id: str
    track: Track | None
    line: bytes


class _Deck:
    def __init__(self, endpoint: Path, poll: float, timeout: float, load_timeout: float) -> None:
        self.endpoint, self.poll, self.timeout, self.load_timeout = (
            endpoint,
            poll,
            timeout,
            load_timeout,
        )
        self.lock = Lock()
        self.stop = Event()
        self.state = DeckState(status=Status.MISSING, change_allowed=False)
        self.request: Request | None = None
        self.command_error = ""
        self.generation = 0
        self.thread = Thread(target=self._run, name=f"xwax-{endpoint.name}", daemon=True)
        self.thread.start()

    def snapshot(self) -> DeckState:
        with self.lock:
            return self.state

    def submit(self, track: Track | None, generation: int | None = None) -> None:
        if track is not None and (track.audio_path is None or not track.available):
            raise ValueError("Choose a real, available audio file for xwax")
        request_id = uuid4().hex
        line = command_line(request_id, track.audio_path if track else None)
        with self.lock:
            if generation is not None and generation != self.generation:
                raise ValueError("Engine reconnected; select the track again to load it")
            if not self.state.can_change_track or self.stop.is_set():
                raise ValueError("Wait for a connected, stopped engine before changing tracks")
            self.request = Request(request_id, track, line)
            self.command_error = ""
            self.state = replace(self.state, status=Status.WAITING, change_allowed=False, error="")

    def _publish(self, snapshot: Snapshot, error: str = "") -> None:
        with self.lock:
            pending = self.request
            if error:
                self.command_error = error
            error = self.command_error
            track = None
            if snapshot.path:
                candidates = (pending.track if pending else None, self.state.track)
                track = next(
                    (t for t in candidates if t and str(t.audio_path) == snapshot.path), None
                )
                if track is None:
                    track = Track(
                        id="xwax:" + snapshot.path,
                        title=Path(snapshot.path).name,
                        artist="Loaded in xwax",
                        duration=snapshot.duration,
                        audio_path=Path(snapshot.path),
                        source_id="xwax",
                    )
                if snapshot.state == "READY":
                    track = replace(track, duration=snapshot.duration)
            status = {
                "EMPTY": Status.EMPTY,
                "IMPORTING": Status.LOADING,
                "READY": Status.PLAYING if snapshot.active else Status.READY,
                "ERROR": Status.ERROR,
            }[snapshot.state]
            if snapshot.result == "PENDING" and snapshot.state != "IMPORTING":
                status = Status.WAITING
            if snapshot.result == "LOCKED":
                error = "Stop the record before changing tracks"
            elif snapshot.result == "ERROR":
                error = "The last engine command failed. Check the file and engine log."
            if snapshot.state == "ERROR":
                error = "xwax failed to decode this file. Check the file and engine log."
            if (
                pending
                and snapshot.request_id == pending.id
                and snapshot.result in {"OK", "LOCKED", "ERROR"}
            ):
                if snapshot.result == "OK":
                    expected = str(pending.track.audio_path) if pending.track else ""
                    expected_state = "READY" if pending.track else "EMPTY"
                    if snapshot.path != expected or snapshot.state != expected_state:
                        raise ProtocolError(
                            "Engine confirmation does not match the requested track"
                        )
                if snapshot.result in {"ERROR", "LOCKED"}:
                    error = (
                        "Stop the record before changing tracks"
                        if snapshot.result == "LOCKED"
                        else "xwax could not load the file. Check the file and engine log."
                    )
                self.request = None
            elif pending and (snapshot.request_id != pending.id or snapshot.state != "IMPORTING"):
                status = Status.WAITING
            if not snapshot.protected:
                error = "Start xwax with --protect before loading tracks"
            mode = (
                "Vinyl tracking"
                if snapshot.timecode_control
                else "Internal playback · Vinyl control disconnected"
            )
            if snapshot.active and snapshot.timecode_control and not snapshot.position_known:
                mode += " · Absolute position unavailable"
            self.state = DeckState(
                track=track,
                status=status,
                position=snapshot.elapsed,
                error=error,
                change_allowed=snapshot.can_change
                and self.request is None
                and not self.stop.is_set(),
                transport_message=mode,
                connection_generation=self.generation,
            )

    def _session(self, connection: Connection) -> None:
        snapshot = connection.status()  # Every connection starts read-only.
        self._publish(snapshot)
        sent_id = ""
        deadline = 0.0
        while not self.stop.is_set():
            with self.lock:
                request = self.request
            if request and request.id != sent_id:
                # Recheck fresh motion immediately before dispatch; --protect also
                # checks inside the engine when the worker applies the command.
                snapshot = connection.status()
                if self.stop.is_set():
                    return
                if not snapshot.can_change:
                    with self.lock:
                        self.request = None
                    self._publish(snapshot, "Engine is moving or importing; track change cancelled")
                else:
                    sent_id, deadline = request.id, monotonic() + self.load_timeout
                    try:
                        connection.command(request.id, request.line)
                    except CommandRejected as error:
                        with self.lock:
                            self.request = None
                        self._publish(snapshot, str(error))
                        continue
            snapshot = connection.status()
            self._publish(snapshot)
            with self.lock:
                waiting = self.request is not None
            if waiting and sent_id and monotonic() >= deadline:
                raise TimeoutError("Load/unload confirmation timed out; outcome unknown")
            self.stop.wait(self.poll)

    def _run(self) -> None:
        connected_once = False
        while not self.stop.is_set():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(self.timeout)
                    sock.connect(str(self.endpoint))
                    connected_once = True
                    with self.lock:
                        self.generation += 1
                    self._session(Connection(sock, self.timeout))
            except (OSError, ProtocolError) as error:
                with self.lock:
                    # Discard even unsent requests: reconnect never replays intent.
                    self.request = None
                    self.command_error = ""
                    self.state = replace(
                        self.state,
                        status=Status.ERROR
                        if isinstance(error, ProtocolError)
                        else Status.DISCONNECTED
                        if connected_once
                        else Status.MISSING,
                        change_allowed=False,
                        error=str(error),
                        transport_message="Engine state unavailable",
                    )
            self.stop.wait(max(self.poll, 0.1))

    def close(self) -> None:
        self.stop.set()
        with self.lock:
            self.request = None
            self.state = replace(self.state, change_allowed=False)
        # Socket operations have deadlines. Never join a worker on the GUI thread.


class XwaxEngine:
    simulation = False

    def __init__(
        self,
        endpoints: tuple[Path, Path],
        *,
        poll: float = 0.1,
        timeout: float = 0.5,
        load_timeout: float = 120.0,
    ) -> None:
        if endpoints[0].absolute() == endpoints[1].absolute():
            raise ValueError("Deck A and B need different engine sockets")
        if any(not math.isfinite(v) or v <= 0 for v in (poll, timeout, load_timeout)):
            raise ValueError("Engine intervals must be positive and finite")
        self._connections = tuple(_Deck(p, poll, timeout, load_timeout) for p in endpoints)
        self._previous = self.decks

    @property
    def decks(self) -> tuple[DeckState, ...]:
        return tuple(deck.snapshot() for deck in self._connections)

    def _deck(self, deck: int) -> _Deck:
        if deck not in (0, 1):
            raise ValueError("Deck must be 0 (A) or 1 (B)")
        return self._connections[deck]

    def load(self, deck: int, track: Track, *, generation: int | None = None) -> None:
        self._deck(deck).submit(track, generation)

    def unload(self, deck: int) -> None:
        self._deck(deck).submit(None)

    def advance(self, seconds: float) -> bool:
        current = self.decks
        changed, self._previous = current != self._previous, current
        return changed

    def close(self) -> None:
        for deck in self._connections:
            deck.close()
