"""Progressive transfers retain ownership after the initial load becomes available."""

import json
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, RLock, Thread
from uuid import uuid4

from pi_dvs.link.media import CacheLease
from pi_dvs.link.nfs import FileInfo
from pi_dvs.model import Track
from pi_dvs.rekordbox.records import ImportCancelled, ImportFailure
from pi_dvs.stream_audio import MAX_HEADER, Layout, UnsupportedAudio, inspect_aiff, write_state

logger = logging.getLogger(__name__)
Progress = Callable[[Path, FileInfo, int], None]
Fetch = Callable[[Event, Progress], Path]


@dataclass(frozen=True)
class PreparedAudio:
    path: Path
    duration: float | None = None
    streaming: bool = False


@dataclass(frozen=True)
class TransferState:
    received: int = 0
    total: int = 0
    status: str = "loading"
    error: str = ""


class _Session:
    def __init__(self, root: Path, fetch: Fetch, lease: CacheLease) -> None:
        self.directory = root / uuid4().hex
        self.descriptor = self.directory / "track.pidvs-stream"
        self.lock = RLock()
        self.cancelled, self.ready, self.finished = Event(), Event(), Event()
        self.layout: Layout | None = None
        self.prepared: PreparedAudio | None = None
        self.state = TransferState()
        self.unsupported = False
        self.waiters = 0
        self.thread = Thread(target=self._run, args=(fetch, lease), name="link-stream", daemon=True)
        self.thread.start()

    def _progress(self, temporary: Path, info: FileInfo, received: int) -> None:
        if self.cancelled.is_set():
            raise ImportCancelled()
        # Layout and files have one producer. Never hold the GUI snapshot lock
        # while reading or publishing files, even on the supposedly local cache.
        if self.layout is None and not self.unsupported:
            with temporary.open("rb") as source:
                header = source.read(min(received, MAX_HEADER))
            try:
                self.layout = inspect_aiff(header, info.size)
            except UnsupportedAudio:
                self.unsupported = True
            if self.layout:
                self.directory.mkdir(parents=True, mode=0o700)
                os.link(temporary, self.directory / "audio.aiff")
                self.descriptor.write_text(json.dumps(self.layout.to_json()), encoding="utf-8")
        if self.layout:
            write_state(self.directory, received, "loading")
        with self.lock:
            self.state = TransferState(received, info.size)
            if self.layout:
                buffer_frames = min(10 * self.layout.rate, self.layout.frames)
                if received >= self.layout.offset + buffer_frames * 4:
                    self.prepared = PreparedAudio(self.descriptor, self.layout.duration, True)
                    self.ready.set()

    def _run(self, fetch: Fetch, lease: CacheLease) -> None:
        try:
            with lease.use():
                self._produce(fetch)
        except (OSError, ImportCancelled, ImportFailure) as error:
            self._failed(str(error) or "Audio session closed")
            self.ready.set()
            self.finished.set()

    def _produce(self, fetch: Fetch) -> None:
        try:
            path = fetch(self.cancelled, self._progress)
            if self.cancelled.is_set():
                raise ImportCancelled()
            size = path.stat().st_size
            if self.layout:
                write_state(self.directory, size, "complete")
            with self.lock:
                self.state = TransferState(size, size, "complete")
                self.prepared = (
                    PreparedAudio(self.descriptor, self.layout.duration, True)
                    if self.layout
                    else PreparedAudio(path)
                )
        except (OSError, ValueError, ImportCancelled) as error:
            self._failed(str(error) or "Download cancelled or USB disconnected")
        except Exception:
            logger.exception("Progressive audio transfer failed")
            self._failed("Audio download failed; see the application log")
        finally:
            self.ready.set()
            self.finished.set()

    def _failed(self, error: str) -> None:
        with self.lock:
            self.state = TransferState(self.state.received, self.state.total, "failed", error)
            received = self.state.received
        if self.layout and self.directory.exists():
            try:
                write_state(self.directory, received, "failed", error)
            except OSError:
                logger.exception("Cannot publish failed audio stream state")

    def wait(self, cancelled: Event) -> PreparedAudio:
        try:
            while not self.ready.wait(0.05):
                if cancelled.is_set():
                    raise ImportCancelled()
            if cancelled.is_set():
                raise ImportCancelled()
            with self.lock:
                if self.state.status == "failed":
                    raise ImportFailure(self.state.error)
                assert self.prepared is not None
                return self.prepared
        finally:
            with self.lock:
                self.waiters -= 1


class Streams:
    """Own producers, cancellation and private files independently of GUI jobs."""

    def __init__(self, root: Path, lease: CacheLease) -> None:
        self.root, self.lease = root, lease
        self.lock = RLock()
        self.sessions: dict[str, _Session] = {}
        self.closed = False
        self._pins: tuple[Track, ...] = ()
        self._preparing: tuple[str, ...] = ()
        self._authoritative = False
        self._wake, self._stop = Event(), Event()
        self._janitor: Thread | None = None

    def _start_cleaner(self) -> None:
        if self._janitor is None and not self.closed:
            self._janitor = Thread(target=self._clean, name="link-stream-cleanup", daemon=True)
            self._janitor.start()

    def prepare(self, track: Track, cancelled: Event, fetch: Fetch) -> PreparedAudio:
        with self.lock:
            if self.closed or cancelled.is_set():
                raise ImportCancelled()
            self._start_cleaner()
            session = self.sessions.get(track.id)
            if session is not None:
                with session.lock:
                    if session.finished.is_set() and (
                        session.state.status == "failed"
                        or (session.prepared is not None and not session.prepared.streaming)
                    ):
                        # Failed streams get a fresh descriptor; ordinary cached
                        # files must re-enter serialized admission/verification.
                        session = None
            if session is None:
                session = _Session(self.root, fetch, self.lease)
                self.sessions[track.id] = session
            with session.lock:
                session.waiters += 1
        return session.wait(cancelled)

    def state(self, track: Track) -> TransferState | None:
        with self.lock:
            session = self.sessions.get(track.id)
            if session is None or (track.streaming and track.audio_path != session.descriptor):
                return None
            with session.lock:
                return session.state

    def protect(
        self, tracks: tuple[Track, ...], *, authoritative: bool, preparing: tuple[str, ...] = ()
    ) -> None:
        """GUI publishes confirmed ownership; cleanup I/O stays on its worker."""
        with self.lock:
            self._start_cleaner()
            changed = (tracks, preparing, authoritative) != (
                self._pins,
                self._preparing,
                self._authoritative,
            )
            self._preparing = preparing
            self._pins = tracks
            self._authoritative = authoritative
        if changed:
            self._wake.set()

    def _clean(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.2)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                with self.lease.use():
                    self._retire()
            except (ImportCancelled, ImportFailure):
                return
            except OSError:
                logger.exception("Cannot retire an unused progressive stream")

    def _retire(self) -> None:
        retired = []
        with self.lock:
            ids = set(self._preparing)
            paths = {t.audio_path for t in self._pins if t.audio_path is not None}
            for key, session in tuple(self.sessions.items()):
                with session.lock:
                    if key in ids or session.descriptor in paths or session.waiters:
                        continue
                    session.cancelled.set()
                    if session.finished.is_set():
                        # Claim retirement before I/O. A new request for the same
                        # track gets a fresh session directory, never this one.
                        retired.append(session.directory)
                        del self.sessions[key]
        for directory in retired:
            shutil.rmtree(directory, ignore_errors=True)
        # Orphans from an earlier app must also respect confirmed native paths.
        if self.root.exists():
            for directory in self.root.iterdir():
                if not directory.is_dir():
                    continue
                with self.lock:
                    if not self._authoritative:
                        return
                    owned = {s.directory for s in self.sessions.values()}
                    pinned = {t.audio_path.parent for t in self._pins if t.audio_path}
                    keep = directory in owned | pinned
                if not keep:
                    shutil.rmtree(directory)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            self._stop.set()
            self._wake.set()
            for session in self.sessions.values():
                session.cancelled.set()
        # Do not delete descriptors here: a separately running engine can still
        # own them. Importers observe failure (or their bounded producer timeout).
