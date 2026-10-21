"""Media generations and a bounded host cache. No network or GUI dependencies."""

import fcntl
import hashlib
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, RLock
from typing import TextIO

from pi_dvs.library import Library
from pi_dvs.link.nfs import Cancellation, Download
from pi_dvs.model import Track
from pi_dvs.rekordbox.records import ImportCancelled, ImportFailure


@dataclass(frozen=True)
class Media:
    key: str
    name: str
    token: str
    source_id: str = field(default_factory=lambda: "link-" + uuid.uuid4().hex)
    root: Path | None = None
    address: str = ""
    cancelled: Event = field(default_factory=Event, compare=False)


@dataclass(frozen=True)
class SourceView:
    media: Media
    library: Library | None
    error: str = ""


class Sources:
    def __init__(self) -> None:
        self.lock = RLock()
        self.revision = 0
        self._current: dict[str, SourceView] = {}
        self._generations: dict[str, Media] = {}

    def observe(
        self, key: str, name: str, token: str, *, root: Path | None = None, address: str = ""
    ) -> Media:
        with self.lock:
            previous = self._current.get(key)
            if previous and not previous.media.cancelled.is_set() and previous.media.token == token:
                return previous.media
            if previous:
                previous.media.cancelled.set()
            media = Media(key, name, token, root=root, address=address)
            self._current[key] = SourceView(media, None)
            self._generations[media.source_id] = media
            self.revision += 1
            return media

    def disconnect(
        self, key: str, reason: str = "USB disconnected", *, expected: Media | None = None
    ) -> None:
        with self.lock:
            view = self._current.get(key)
            if (
                view
                and (expected is None or view.media is expected)
                and not view.media.cancelled.is_set()
            ):
                view.media.cancelled.set()
                self._current[key] = replace(view, error=reason)
                self.revision += 1

    def install(self, media: Media, library: Library) -> None:
        """Commit a staged local import only after its caller accepts the result."""
        with self.lock:
            if media.cancelled.is_set():
                raise ImportCancelled()
            previous = self._current.get(media.key)
            if previous and previous.media is not media:
                previous.media.cancelled.set()
            self._current[media.key] = SourceView(media, library)
            self._generations[media.source_id] = media
            self.revision += 1

    def publish(self, media: Media, library: Library) -> None:
        with self.lock:
            if media.cancelled.is_set() or self._current[media.key].media is not media:
                raise ImportCancelled()
            self._current[media.key] = SourceView(media, library)
            self.revision += 1

    def fail(self, media: Media, error: str) -> None:
        with self.lock:
            if not media.cancelled.is_set():
                self._current[media.key] = replace(self._current[media.key], error=error)
                self.revision += 1

    def views(self) -> tuple[SourceView, ...]:
        with self.lock:
            return tuple(self._current.values())

    def view(self, key: str) -> SourceView:
        with self.lock:
            return self._current[key]

    def media(self, source_id: str) -> Media:
        with self.lock:
            return self._generations[source_id]

    def close(self) -> None:
        with self.lock:
            for media in self._generations.values():
                media.cancelled.set()
            self.revision += 1


def relabel(library: Library, media: Media) -> Library:
    ids = {track.id: f"{media.source_id}:{track.export_id}" for track in library.tracks}
    return Library(
        tuple(replace(t, id=ids[t.id], source_id=media.source_id) for t in library.tracks),
        tuple(replace(p, track_ids=tuple(ids[i] for i in p.track_ids)) for p in library.playlists),
        name=media.name,
        source_id=media.source_id,
        format_name=library.format_name,
        warnings=library.warnings,
    )


class Cancel:
    def __init__(self, *events: Cancellation) -> None:
        self.events = events

    def is_set(self) -> bool:
        return any(event.is_set() for event in self.events)

    def check(self) -> None:
        if self.is_set():
            raise ImportCancelled()


class AudioCache:
    """Only complete files are reusable; pins cover queued loads and confirmed decks."""

    def __init__(self, root: Path, limit: int = 2 * 1024**3) -> None:
        self.root = root
        self.limit = limit
        self.lock = RLock()
        self._pinned: set[str] = set()
        self._verified: dict[str, tuple[int, str]] = {}

    @staticmethod
    def name(track: Track) -> str:
        return (
            ".audio-"
            + hashlib.sha256(track.id.encode()).hexdigest()
            + Path(track.relative_path).suffix.lower()
        )

    def protect(self, tracks: tuple[Track, ...]) -> None:
        with self.lock:
            self._pinned = {self.name(track) for track in tracks}
            # Reconnected xwax may know only the path, with a synthetic track ID.
            self._pinned.update(
                track.audio_path.name
                for track in tracks
                if track.audio_path is not None
                and track.audio_path.parent == self.root
                and track.audio_path.name.startswith(".audio-")
            )

    def materialize(
        self, track: Track, size: int, fetch: Callable[[Path], Download], cancelled: Cancel
    ) -> Path:
        # The service serializes transfers. Only pin decisions take the GUI lock;
        # filesystem scans, hashes and deletion stay on this worker.
        self.root.mkdir(parents=True, exist_ok=True)
        name = self.name(track)
        target = self.root / name
        cancelled.check()
        expected = self._verified.get(name)
        if expected and target.is_file():
            checksum = hashlib.sha256()
            with target.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    cancelled.check()
                    checksum.update(block)
            if target.stat().st_size == expected[0] == size and checksum.hexdigest() == expected[1]:
                cancelled.check()
                os.utime(target, None)
                return target
        if target.exists():
            with self.lock:
                if name in self._pinned and expected:
                    raise ImportFailure("Cached audio changed while a deck may be using it")
            target.unlink()
        entries = sorted(self.root.glob(".audio-*"), key=lambda p: p.stat().st_mtime_ns)
        # Progressive prefixes may remain pinned by a separate native engine,
        # including after app restart. Count their storage without counting a
        # completed cache file's hardlink twice; never evict a live prefix.
        sizes = {(p.stat().st_dev, p.stat().st_ino): p.stat().st_size for p in entries}
        retained = set()
        for partial in (self.root / ".streams").glob("*/audio.aiff"):
            try:
                stat = partial.stat()
            except FileNotFoundError:
                continue  # The stream janitor retired this unpinned session.
            identity = (stat.st_dev, stat.st_ino)
            sizes[identity] = stat.st_size
            retained.add(identity)
        used = sum(sizes.values())
        if size > self.limit:
            raise ImportFailure("Track exceeds the audio cache capacity")
        for path in entries:
            if used + size <= self.limit:
                break
            stat = path.stat()
            with self.lock:
                evict = path.name not in self._pinned and (stat.st_dev, stat.st_ino) not in retained
                if evict:
                    # Claim before unlinking. A new GUI request must go through
                    # the serialized materializer before obtaining this file.
                    self._verified.pop(path.name, None)
            if evict:
                used -= stat.st_size
                path.unlink()
        if used + size > self.limit:
            raise ImportFailure(
                "Audio cache is full; unload an unused deck or increase --link-cache-mib"
            )
        result = fetch(target)
        if cancelled.is_set():
            target.unlink(missing_ok=True)
            raise ImportCancelled()
        if result.size != size:
            target.unlink(missing_ok=True)
            raise ImportFailure("Audio size changed during download")
        self._verified[name] = (result.size, result.sha256)
        os.utime(target, (time.time(), time.time()))
        return target


class CacheLease:
    """One application owns the cache until all cancelled workers have exited."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = RLock()
        self.stream: TextIO | None = None
        self.active = 0
        self.closed = False

    @contextmanager
    def use(self) -> Iterator[None]:
        with self.lock:
            if self.closed:
                raise ImportCancelled()
            if self.stream is None:
                self.root.mkdir(parents=True, exist_ok=True)
                stream = (self.root / "owner.lock").open("a")
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    stream.close()
                    raise ImportFailure(
                        "Link cache is in use by another pi-dvs instance"
                    ) from error
                try:
                    # The exclusive lease proves no previous process still owns
                    # an in-flight transfer. Crash leftovers never become audio.
                    for partial in (self.root / "audio").glob(".partial-*"):
                        partial.unlink(missing_ok=True)
                except OSError:
                    stream.close()
                    raise
                self.stream = stream
            self.active += 1
        try:
            yield
        finally:
            with self.lock:
                self.active -= 1
                if self.closed and self.active == 0 and self.stream:
                    self.stream.close()
                    self.stream = None

    def close(self) -> None:
        with self.lock:
            self.closed = True
            if self.active == 0 and self.stream:
                self.stream.close()
                self.stream = None
