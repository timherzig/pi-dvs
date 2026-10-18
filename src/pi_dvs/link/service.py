"""Background Link helper supervision, USB lifecycle and serialized file retrieval."""

import hashlib
import json
import logging
import os
import select
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Event, Lock, RLock, Thread
from typing import Any

from pi_dvs.library import Library
from pi_dvs.link.catalog import local_token, remote_library, serving_catalog
from pi_dvs.link.covers import MAX_COVER_BYTES, CoverCancel, Covers
from pi_dvs.link.media import AudioCache, CacheLease, Cancel, Media, Sources, relabel
from pi_dvs.link.nfs import Client, Download
from pi_dvs.link.power import prevent_idle_sleep
from pi_dvs.model import Track
from pi_dvs.rekordbox import MAX_DATABASE_BYTES, import_library, media_path
from pi_dvs.rekordbox.records import ImportCancelled, ImportFailure

logger = logging.getLogger(__name__)


class LinkService:
    def __init__(
        self, interface: str, helper: Path, cache: Path, *, cache_bytes: int = 2 * 1024**3
    ) -> None:
        cache = cache.expanduser().resolve()
        self.interface, self.helper, self.cache_root = interface, helper, cache
        self._lease = CacheLease(cache)
        self.sources = Sources()
        self.audio = AudioCache(cache / "audio", cache_bytes)
        self.covers = Covers(cache / "remote-covers")
        self.stop = Event()
        self._lock = RLock()
        self._transfers = Lock()
        self._status = "Starting Pro DJ Link…"
        self._address = ""
        self._last_report = 0.0
        self._process: subprocess.Popen[str] | None = None
        self._instance = ""
        self._locals: dict[str, tuple[Path, str, str, dict[str, object]]] = {}
        self._staged: dict[str, tuple[Media, Library, Event]] = {}
        self._selected_local: str | None = None
        self._command: dict[str, object] | None = None
        self._command_revision = 0
        self._db_identity: dict[str, tuple[int, ...]] = {}
        self._worker: Thread | None = None

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def start(self) -> None:
        if self._worker is None:
            self._worker = Thread(target=self._run, name="pi-dvs-link", daemon=True)
            self._worker.start()

    def _set_status(self, status: str) -> None:
        with self._lock:
            self._status = status

    @contextmanager
    def _transfer(self, cancelled: Cancel) -> Iterator[None]:
        while not self._transfers.acquire(timeout=0.05):
            cancelled.check()
        try:
            cancelled.check()
            yield
        finally:
            self._transfers.release()

    def import_local(self, root: Path, choice: str, event: Event) -> Library:
        with self._lease.use():
            return self._import_local(root, choice, event)

    def _import_local(self, root: Path, choice: str, event: Event) -> Library:
        root = root.expanduser().resolve()
        before = local_token(root)
        library = import_library(
            root, self.cache_root / "artwork", format_choice=choice, cancelled=event
        )
        catalog = serving_catalog(library, root)
        if before != local_token(root):
            raise ImportFailure("USB changed while its library was being read; retry")
        Cancel(event, self.stop).check()
        key = "local:" + str(root)
        token = before + ":" + library.source_id + ":" + library.format_name
        current = next((v.media for v in self.sources.views() if v.media.key == key), None)
        media = (
            current
            if current and current.token == token and not current.cancelled.is_set()
            else Media(key, root.name, token, root=root)
        )
        library = relabel(library, media)
        catalog["generation"] = int(media.source_id.removeprefix("link-")[:8], 16) & 0x7FFFFFFF
        with self._lock:
            Cancel(event, self.stop).check()
            self._locals[media.source_id] = (root, choice, before, catalog)
            self._staged[media.source_id] = (media, library, event)
        return library

    def accept_local(self, source_id: str) -> Media:
        # No I/O here: called only after a Jobs/UI or guarded watcher acceptance.
        with self._lock:
            media, library, event = self._staged[source_id]
            Cancel(event, self.stop, media.cancelled).check()
            self.sources.install(media, library)
            if self._selected_local == source_id and self._command is not None:
                return media
            self._selected_local = source_id
            self._command = self._locals[source_id][3]
            self._command_revision += 1
            return media

    def accept_library(self, library: Library) -> Media:
        with self._lock:
            if library.source_id in self._staged:
                return self.accept_local(library.source_id)
        return self.sources.media(library.source_id)

    def refresh_source(self, key: str) -> None:
        media = self.sources.view(key).media
        if media.address and not media.cancelled.is_set():
            self.sources.disconnect(key, "Refreshing CDJ USB")
            self.sources.observe(key, media.name, media.token, address=media.address)

    def catalog(self, key: str, event: Event, *, refresh: bool = False) -> Library:
        with self._lease.use():
            return self._catalog(key, event, refresh=refresh)

    def _catalog(self, key: str, event: Event, *, refresh: bool = False) -> Library:
        view = self.sources.view(key)
        media = view.media
        cancelled = Cancel(event, media.cancelled, self.stop)
        cancelled.check()
        if media.root:
            with self._lock:
                choice = self._locals.get(media.source_id, (media.root, "auto", "", {}))[1]
            return self.import_local(media.root, choice, event)
        if view.library is not None and not refresh:
            return view.library
        with self._transfer(cancelled):
            with self._lock:
                address = self._address
            self.cache_root.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix="catalog-", dir=self.cache_root) as temp:
                with Client(address, cancelled=cancelled) as client:
                    client.mount(media.address)
                    path = Path(temp) / "export.pdb"
                    result = client.download(
                        "/PIONEER/rekordbox/export.pdb", path, max_bytes=MAX_DATABASE_BYTES
                    )
                    library = remote_library(path.read_bytes(), media)
                cancelled.check()
                self.sources.publish(media, library)
                with self._lock:
                    self._db_identity[media.source_id] = result.identity
                return library

    def available(self, track: Track) -> bool:
        try:
            return not self.sources.media(track.source_id).cancelled.is_set()
        except KeyError:
            return False

    def prepare(self, track: Track, event: Event) -> Path:
        with self._lease.use():
            return self._prepare(track, event)

    def _prepare(self, track: Track, event: Event) -> Path:
        try:
            media = self.sources.media(track.source_id)
        except KeyError as error:
            raise ImportFailure("This media generation is no longer available") from error
        cancelled = Cancel(event, media.cancelled, self.stop)
        cancelled.check()
        if not track.available:
            raise ImportFailure(track.unavailable_reason)
        with self._transfer(cancelled):
            if media.root:
                return self._local_audio(track, media, cancelled)
            with self._lock:
                address = self._address
                identity = self._db_identity.get(media.source_id)
            with Client(address, cancelled=cancelled) as client:
                client.mount(media.address)
                database = client.lookup("/PIONEER/rekordbox/export.pdb")
                if identity is None or database.identity != identity:
                    self.sources.disconnect(
                        media.key, "CDJ USB changed; refresh its library", expected=media
                    )
                    raise ImportFailure("CDJ USB changed; refresh its library")
                info = client.lookup(track.relative_path)

                def fetch(path: Path) -> Download:
                    return client.download(
                        track.relative_path, path, expected_identity=info.identity
                    )

                path = self.audio.materialize(track, info.size, fetch, cancelled)
                if client.lookup("/PIONEER/rekordbox/export.pdb").identity != identity:
                    self.sources.disconnect(
                        media.key, "CDJ USB changed during download", expected=media
                    )
                    raise ImportFailure("CDJ USB changed during download")
                cancelled.check()
                return path

    def cover(self, track: Track, event: Event) -> Path | None:
        """Optional, low-priority artwork; never changes a loaded audio track."""
        media = self.sources.media(track.source_id)
        cancelled = Cancel(event, media.cancelled, self.stop)
        cancelled.check()
        if media.root or not track.artwork_path:
            return track.artwork
        key = (media.source_id, track.artwork_path)
        with self._lease.use():
            cached = self.covers.find(key)
            if cached is not None:
                return cached
            try:
                original = media_path(Path("/pi-dvs-remote"), track.artwork_path)
                relative = original.relative_to("/pi-dvs-remote")
                bounded = CoverCancel(cancelled)
                for candidate in (relative.with_stem(relative.stem + "_m"), relative):
                    try:
                        with self._transfer(bounded):
                            with self._lock:
                                address = self._address
                                identity = self._db_identity.get(media.source_id)
                            with Client(address, cancelled=bounded) as client:
                                client.mount(media.address)
                                if (
                                    client.lookup("/PIONEER/rekordbox/export.pdb").identity
                                    != identity
                                ):
                                    return None
                                with TemporaryDirectory(
                                    prefix="cover-", dir=self.cache_root
                                ) as temp:
                                    path = Path(temp) / "image"
                                    client.download(str(candidate), path, max_bytes=MAX_COVER_BYTES)
                                    data = path.read_bytes()
                                if (
                                    client.lookup("/PIONEER/rekordbox/export.pdb").identity
                                    != identity
                                ):
                                    return None
                        # Decode pixels outside the network gate; audio retains priority.
                        result = self.covers.store(key, data, cancelled)
                        if result is not None:
                            return result
                    except (OSError, ImportFailure):
                        continue
            except ImportCancelled:
                cancelled.check()  # Propagate real cancellation, not the optional cover deadline.
            except (OSError, ImportFailure):
                pass  # Missing/broken cover leaves the placeholder; audio remains usable.
            return None

    def _local_audio(self, track: Track, media: Media, cancelled: Cancel) -> Path:
        assert media.root is not None
        root = media.root
        with self._lock:
            expected = self._locals[media.source_id][2]
        if local_token(root) != expected:
            self.sources.disconnect(media.key, expected=media)
            raise ImportFailure("USB changed; wait for its fresh library")
        source = media_path(media.root, track.relative_path)
        before = source.stat()
        if before.st_size == 0:
            raise ImportFailure("The audio file is empty")

        def fetch(destination: Path) -> Download:
            temporary: Path | None = None
            checksum = hashlib.sha256()
            try:
                with (
                    source.open("rb") as original,
                    NamedTemporaryFile(
                        dir=destination.parent, prefix=".partial-", delete=False
                    ) as output,
                ):
                    temporary = Path(output.name)
                    while block := original.read(256 * 1024):
                        cancelled.check()
                        output.write(block)
                        checksum.update(block)
                    output.flush()
                    os.fsync(output.fileno())
                    after = os.fstat(original.fileno())
                if (
                    (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_ctime_ns,
                    )
                    != (
                        after.st_dev,
                        after.st_ino,
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    )
                    or local_token(root) != expected
                    or (source.stat().st_dev, source.stat().st_ino)
                    != (before.st_dev, before.st_ino)
                ):
                    raise ImportFailure("USB audio changed while copying")
                cancelled.check()
                os.link(temporary, destination)
                return Download(before.st_size, checksum.hexdigest(), (), 0)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

        result = self.audio.materialize(track, before.st_size, fetch, cancelled)
        if local_token(root) != expected:
            self.sources.disconnect(media.key, expected=media)
            raise ImportFailure("USB changed while preparing audio")
        return result

    def update_peers(self, message: dict[str, Any], instance: str) -> None:
        address = message.get("address")
        players = message.get("players")
        if not isinstance(address, str) or not isinstance(players, list) or len(players) > 32:
            raise ValueError("Invalid Link helper snapshot")
        seen: set[str] = set()
        for player in players:
            if not isinstance(player, dict) or not isinstance(player.get("address"), str):
                raise ValueError("Invalid Link player snapshot")
            mac = player.get("mac", [])
            if (
                not isinstance(mac, list)
                or len(mac) != 6
                or not all(isinstance(n, int) and 0 <= n <= 255 for n in mac)
            ):
                raise ValueError("Invalid Link device identity")
            key = "cdj:" + (bytes(mac).hex() if any(mac) else player["address"])
            seen.add(key)
            if player.get("usb") is True:
                token = f"{instance}:{player['address']}:{player.get('generation')}"
                self.sources.observe(
                    key, f"CDJ {player.get('number')} · USB", token, address=player["address"]
                )
            else:
                self.sources.disconnect(key, "CDJ USB removed or stopped")
        for view in self.sources.views():
            if view.media.address and view.media.key not in seen:
                self.sources.disconnect(view.media.key, "CDJ disconnected")
        with self._lock:
            self._address = address
            self._last_report = time.monotonic()
            failure = message.get("error")
            self._status = (
                str(failure)
                if failure
                else (
                    f"Pro DJ Link · sharing {message.get('tracks', 0)} tracks"
                    if message.get("serving")
                    else "Pro DJ Link · choose a local USB to share"
                )
            )

    def _read(self, process: subprocess.Popen[str], instance: str) -> None:
        assert process.stdout is not None
        try:
            while not self.stop.is_set():
                line = process.stdout.readline(1024 * 1024)
                if not line:
                    break
                if not line.endswith("\n"):
                    raise ValueError("Oversized Link helper snapshot")
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Invalid Link helper snapshot")
                with self._lock:
                    if self._instance != instance or self.stop.is_set():
                        return
                    # The pinned helper serializes LinkState in debug form.
                    # Down is terminal even if the interface later returns;
                    # continuing heartbeats must not hide that failed export.
                    state = message.get("state")
                    if isinstance(state, str) and state.startswith("Down("):
                        raise OSError(f"Link network unavailable: {state}; reconnecting")
                    self.update_peers(message, instance)
        except (OSError, ValueError) as error:
            self._set_status(f"Link helper failed: {error}")
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    def _offline(self, reason: str) -> None:
        for view in self.sources.views():
            if view.media.address:
                self.sources.disconnect(view.media.key, reason)

    def _watch_local(self) -> None:
        with self._lock:
            selected = self._selected_local
            local = self._locals.get(selected or "")
        if not selected or not local:
            return
        root, choice, expected, _ = local
        media = self.sources.media(selected)
        try:
            token = local_token(root)
        except (OSError, ImportFailure):
            if not media.cancelled.is_set():
                self.sources.disconnect(media.key, expected=media)
                with self._lock:
                    if self._selected_local == selected:
                        self._command = None
                        self._command_revision += 1
            return
        if media.cancelled.is_set() or token != expected:
            self.sources.disconnect(
                media.key, "USB changed; reading fresh library…", expected=media
            )
            try:
                library = self.import_local(root, choice, self.stop)
            except (OSError, ImportFailure) as error:
                self._set_status(f"Cannot reconnect USB: {error}")
            else:
                with self._lock:
                    if self._selected_local == selected:
                        self.accept_local(library.source_id)

    def _send(
        self, process: subprocess.Popen[str], revision: int, catalog: dict[str, object] | None
    ) -> None:
        assert process.stdin is not None
        data = (json.dumps(dict(revision=revision, catalog=catalog)) + "\n").encode("utf-8")
        if len(data) > 32 * 1024**2:
            raise ValueError("Link catalog exceeds the helper's 32 MiB command limit")
        fd = process.stdin.fileno()
        os.set_blocking(fd, False)
        pending = memoryview(data)
        deadline = time.monotonic() + 5
        while pending:
            Cancel(self.stop).check()
            if time.monotonic() >= deadline:
                raise TimeoutError("Link helper stopped accepting its catalog; reconnecting")
            if not select.select([], [fd], [], 0.1)[1]:
                continue
            try:
                written = os.write(fd, pending[:65536])
            except BlockingIOError:
                continue
            pending = pending[written:]

    def _run(self) -> None:
        try:
            with self._lease.use(), prevent_idle_sleep():
                self._supervise()
        except (ImportFailure, OSError) as error:
            self._set_status(f"Pro DJ Link unavailable: {error}")
        except ImportCancelled:
            pass

    def _supervise(self) -> None:
        delay = 1.0
        while not self.stop.is_set():
            process = None
            try:
                self.cache_root.mkdir(parents=True, exist_ok=True)
                log = self.cache_root / "link-helper.log"
                if log.exists() and log.stat().st_size > 2 * 1024**2:
                    log.replace(log.with_suffix(".previous.log"))
                with log.open("a") as errors:
                    process = subprocess.Popen(
                        [str(self.helper), self.interface],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=errors,
                        text=True,
                        encoding="utf-8",
                        env={**os.environ, "RUST_LOG": "error"},
                    )
                with self._lock:
                    self._process = process
                    self._instance = uuid.uuid4().hex
                    self._last_report = time.monotonic()
                    instance = self._instance
                Thread(
                    target=self._read,
                    args=(process, instance),
                    name="pi-dvs-link-status",
                    daemon=True,
                ).start()
                sent = -1
                while not self.stop.wait(0.2) and process.poll() is None:
                    self._watch_local()
                    with self._lock:
                        revision, catalog = self._command_revision, self._command
                        last_report = self._last_report
                    if sent != revision:
                        assert process.stdin is not None
                        self._send(process, revision, catalog)
                        sent = revision
                    if time.monotonic() - last_report > 6:
                        raise TimeoutError("Link helper stopped reporting; reconnecting")
                    delay = 1.0
                if not self.stop.is_set():
                    raise OSError(f"Link helper exited ({process.poll()}); retrying")
            except ImportCancelled:
                break
            except (OSError, ValueError) as error:
                logger.warning("Pro DJ Link: %s", error)
                self._set_status(f"Pro DJ Link unavailable: {error}")
            finally:
                self._offline("Link connection lost")
                if process:
                    if process.stdin:
                        try:
                            process.stdin.close()
                        except BrokenPipeError:
                            pass
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=2)
                    if process.stdout:
                        process.stdout.close()
                with self._lock:
                    self._process = None
            if self.stop.wait(delay):
                break
            delay = min(10, delay * 2)

    def close(self) -> None:
        self.stop.set()
        self.sources.close()
        Thread(target=self._lease.close, name="pi-dvs-cache-close", daemon=True).start()
        # Never wait for network or process shutdown on the Qt thread.
