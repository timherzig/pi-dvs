"""Qt models and user actions. Audio-independent behavior lives in the engine."""

from dataclasses import replace
from functools import partial
from pathlib import Path
from time import monotonic

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)

from pi_dvs.engine import DemoEngine, Engine
from pi_dvs.jobs import JobKind, Jobs
from pi_dvs.library import Library
from pi_dvs.link.service import LinkService
from pi_dvs.link.streams import PreparedAudio
from pi_dvs.model import Status, Track
from pi_dvs.rekordbox import import_library, prepare_audio
from pi_dvs.rekordbox.records import ImportCancelled


def time_label(seconds: float) -> str:
    sign = "−" if seconds < 0 else ""
    minutes, seconds = divmod(int(abs(seconds)), 60)
    return f"{sign}{minutes:02}:{seconds:02}"


def artwork_url(track: Track | None) -> str:
    if track and track.artwork and (track.source_id != "demo" or track.artwork.is_file()):
        return track.artwork.as_uri()
    return ""


class TrackListModel(QAbstractListModel):
    _roles = (
        "trackId",
        "trackTitle",
        "artist",
        "duration",
        "artwork",
        "available",
        "detail",
        "unavailableReason",
    )

    def __init__(self, tracks: tuple[Track, ...], parent: QObject) -> None:
        super().__init__(parent)
        self._tracks = tracks
        self._covers: dict[str, Path] = {}

    def artwork(self, track: Track | None) -> str:
        if track and track.id in self._covers:
            return self._covers[track.id].as_uri()
        return artwork_url(track)

    def forget_evicted_covers(self, paths: frozenset[Path]) -> set[str]:
        removed = {key for key, path in self._covers.items() if path not in paths}
        for key in removed:
            self._covers.pop(key)
        if removed and self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, 0),
                [int(Qt.ItemDataRole.UserRole) + 4],
            )
        return removed

    def remember_cover(self, track: Track, path: Path, pinned: set[str]) -> None:
        if len(self._covers) >= 1024 and track.id not in self._covers:
            self._covers.pop(next(key for key in self._covers if key not in pinned))
        self._covers[track.id] = path
        for row, item in enumerate(self._tracks):
            if item.id == track.id:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index, [int(Qt.ItemDataRole.UserRole) + 4])

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            int(Qt.ItemDataRole.UserRole) + i: QByteArray(name.encode())
            for i, name in enumerate(self._roles)
        }

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._tracks)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | bool | None:
        if not index.isValid() or not 0 <= index.row() < len(self._tracks):
            return None
        track = self._tracks[index.row()]
        values = (
            track.id,
            track.title,
            track.artist,
            time_label(track.duration),
            self.artwork(track),
            track.available,
            " · ".join(
                v for v in (track.album, f"{track.bpm:g} BPM" if track.bpm else "", track.key) if v
            ),
            track.unavailable_reason,
        )
        offset = role - int(Qt.ItemDataRole.UserRole)
        return values[offset] if 0 <= offset < len(values) else None

    def replace_tracks(self, tracks: tuple[Track, ...]) -> None:
        self.beginResetModel()
        self._tracks = tracks
        self.endResetModel()


class Controller(QObject):
    decksChanged = Signal()
    searchChanged = Signal()
    noticeChanged = Signal()
    libraryChanged = Signal()
    browserChanged = Signal()
    importingChanged = Signal()
    sourcesChanged = Signal()
    linkChanged = Signal()

    def __init__(
        self,
        library: Library,
        engine: Engine,
        cache: Path | None = None,
        link: LinkService | None = None,
    ) -> None:
        super().__init__()
        self._library = library
        self._engine = engine
        self._link = link
        self._source_key = ""
        self._requested_source = ""
        self._pending_import_generation = ""
        self._sources_revision = -1
        self._link_status = ""
        self._submitted: dict[int, Track] = {}
        if link:
            link.start()
        self._cache = (
            cache
            or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
            / "artwork"
        )
        self._jobs = Jobs(self)
        self._jobs.completed.connect(self._completed)
        self._importing = False
        self._source_root: Path | None = None
        self._format_choice = "auto"
        self._pending_source: tuple[Path, str] | None = None
        self._category = "tracks"
        self._selection = ""
        self._history: list[tuple[str, str]] = []
        self._preparing: dict[int, tuple[Track, int]] = {}
        self._cover_requests: dict[int, tuple[Track, int]] = {}
        self._cover_attempts: dict[int, tuple[str, int]] = {}
        self._browse = library.browse("tracks")
        self._query = ""
        self._notice = ""
        self._model = TrackListModel(self._browse.tracks, self)
        self._last_tick = monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @Property(bool, constant=True)
    def linkEnabled(self) -> bool:
        return self._link is not None

    @Property(str, notify=linkChanged)
    def linkStatus(self) -> str:
        return self._link_status

    @Property(list, notify=sourcesChanged)
    def sources(self) -> list[dict[str, str]]:
        if self._link is None:
            return []
        return [
            dict(
                key=v.media.key,
                name=v.media.name + (" · disconnected" if v.media.cancelled.is_set() else ""),
            )
            for v in self._link.sources.views()
        ]

    @Property(int, notify=sourcesChanged)
    def selectedSourceIndex(self) -> int:
        return (
            next(
                (
                    i
                    for i, v in enumerate(self._link.sources.views())
                    if v.media.key == (self._requested_source or self._source_key)
                ),
                -1,
            )
            if self._link
            else -1
        )

    @Property(bool, notify=libraryChanged)
    def localSource(self) -> bool:
        return self._source_root is not None

    @Slot(str)
    def selectSource(self, key: str) -> None:
        self._open_source(key)

    def _open_source(self, key: str, refresh: bool = False) -> None:
        link = self._link
        if link is None:
            return
        try:
            if refresh:
                link.refresh_source(key)
            view = link.sources.view(key)
        except KeyError:
            return
        self._jobs.cancel(JobKind.IMPORT)
        self._requested_source = key
        self._pending_import_generation = view.media.source_id
        self._pending_source = None
        self._importing = not view.media.cancelled.is_set()
        self.importingChanged.emit()
        self.sourcesChanged.emit()
        if not self._importing:
            self._set_notice(f"{view.media.name} disconnected; waiting to reconnect")
            return
        self._set_notice(f"Reading {view.media.name}…")
        self._jobs.submit(JobKind.IMPORT, lambda event: link.catalog(key, event, refresh=refresh))

    @Property(QObject, constant=True)
    def libraryModel(self) -> TrackListModel:
        return self._model

    @Property(int, notify=searchChanged)
    def trackCount(self) -> int:
        return self._model.rowCount()

    @Property(int, notify=libraryChanged)
    def totalTracks(self) -> int:
        return len(self._library.tracks)

    def _get_query(self) -> str:
        return self._query

    def _set_query(self, value: str) -> None:
        if value != self._query:
            self._query = value
            self._refresh_browser()

    query = Property(str, _get_query, _set_query, notify=searchChanged)

    def _refresh_browser(self) -> None:
        self._browse = self._library.browse(self._category, self._selection, self._query)
        self._model.replace_tracks(self._browse.tracks)
        self.searchChanged.emit()
        self.browserChanged.emit()

    @Property(str, notify=libraryChanged)
    def libraryName(self) -> str:
        return f"{self._library.name} · {self._library.format_name}"

    @Property(bool, constant=True)
    def isSimulation(self) -> bool:
        return self._engine.simulation

    @Property(bool, notify=libraryChanged)
    def isDemo(self) -> bool:
        return self._library.source_id == "demo"

    @Property(str, notify=browserChanged)
    def category(self) -> str:
        return self._category

    @Property(str, notify=browserChanged)
    def browseTitle(self) -> str:
        return self._browse.title

    @Property(str, notify=browserChanged)
    def browsePath(self) -> str:
        titles = [
            self._library.browse(category, selection).title for category, selection in self._history
        ]
        return " › ".join([*titles, self._browse.title])

    @Property(bool, notify=browserChanged)
    def trackView(self) -> bool:
        return self._browse.is_tracks

    @Property(list, notify=browserChanged)
    def browseEntries(self) -> list[dict[str, str]]:
        return [dict(entryId=e.id, name=e.name, detail=e.detail) for e in self._browse.entries]

    @Property(bool, notify=browserChanged)
    def canGoBack(self) -> bool:
        return bool(self._history)

    @Property(bool, notify=importingChanged)
    def importing(self) -> bool:
        return self._importing

    @Property(bool, notify=importingChanged)
    def canCancelImport(self) -> bool:
        if self._importing:
            return True
        if not self._link or not self._requested_source:
            return False
        media = self._link.sources.view(self._requested_source).media
        return media.cancelled.is_set() or media.source_id != self._library.source_id

    @Slot(str)
    def browseCategory(self, category: str) -> None:
        if category not in ("tracks", "playlists", "artists", "albums", "genres", "bpm", "keys"):
            return
        self._category, self._selection = category, ""
        self._history.clear()
        self._query = ""
        self._refresh_browser()

    @Slot(str)
    def openEntry(self, entry_id: str) -> None:
        if not any(e.id == entry_id for e in self._browse.entries):
            return
        self._history.append((self._category, self._selection))
        self._selection = entry_id
        self._query = ""
        self._refresh_browser()

    @Slot()
    def goBack(self) -> None:
        if self._history:
            self._category, self._selection = self._history.pop()
            self._query = ""
            self._refresh_browser()

    @Slot(int, result=str)
    def trackIdAt(self, index: int) -> str:
        return self._browse.tracks[index].id if 0 <= index < len(self._browse.tracks) else ""

    @Slot(str, str)
    def openExport(self, url: str, format_choice: str = "auto") -> None:
        selected = QUrl(url)
        root = Path(selected.toLocalFile() if selected.isLocalFile() else url)
        self._pending_source = (root, format_choice)
        self._requested_source = ""
        self._pending_import_generation = ""
        self._importing = True
        self.importingChanged.emit()
        self._set_notice("")
        link = self._link
        self._jobs.submit(
            JobKind.IMPORT,
            (lambda event: link.import_local(root, format_choice, event))
            if link
            else (
                lambda event: import_library(
                    root, self._cache, format_choice=format_choice, cancelled=event
                )
            ),
        )

    @Slot()
    def refreshExport(self) -> None:
        if self._link and (self._requested_source or self._source_key):
            self._open_source(self._requested_source or self._source_key, refresh=True)
        elif self._source_root:
            self.openExport(str(self._source_root), self._format_choice)

    @Slot(str)
    def changeFormat(self, format_choice: str) -> None:
        root = self._source_root
        if self._importing and self._pending_source:
            root = self._pending_source[0]
        if root:
            self.openExport(str(root), format_choice)

    @Slot()
    def cancelImport(self) -> None:
        self._jobs.cancel(JobKind.IMPORT)
        self._requested_source = ""
        self._pending_import_generation = ""
        self._importing = False
        self.importingChanged.emit()
        self.sourcesChanged.emit()
        self._set_notice("Library selection cancelled")

    @Slot(object, object, str)
    def _completed(self, operation: JobKind, result: object, error: str) -> None:
        deck = operation.deck
        if operation.cover:
            assert deck is not None
            pending_cover = self._cover_requests.pop(deck, None)
            current = self._engine.decks[deck]
            if (
                pending_cover
                and current.track
                and current.track.id == pending_cover[0].id
                and current.connection_generation == pending_cover[1]
                and isinstance(result, Path)
            ):
                self._model.remember_cover(
                    pending_cover[0],
                    result,
                    {s.track.id for s in self._engine.decks if s.track},
                )
                self._pin_covers()
                self.decksChanged.emit()
            return
        if deck is None:
            self._importing = False
            self.importingChanged.emit()
            if isinstance(result, Library):
                if self._link:
                    try:
                        media = self._link.accept_library(result)
                    except ImportCancelled:
                        self._set_notice("USB import was cancelled")
                        return
                    if media.cancelled.is_set():
                        self._set_notice("USB disconnected before its library was ready")
                        return
                    self._source_key = media.key
                    self._requested_source = media.key
                    self._pending_import_generation = media.source_id
                    self._source_root = media.root
                    self.sourcesChanged.emit()
                self._library = result
                if self._pending_source:
                    self._source_root, self._format_choice = self._pending_source
                self.browseCategory("tracks")
                self.libraryChanged.emit()
                self._set_notice(" ".join(result.warnings))
            else:
                self._set_notice(error)
            self.importingChanged.emit()
            return
        pending = self._preparing.pop(deck, None)
        if error:
            self._set_notice(f"Cannot load audio: {error}")
        elif pending:
            track, generation = pending
            if self._link and not self._link.available(track):
                self._set_notice("USB disconnected before the download completed")
                self.decksChanged.emit()
                return
            try:
                prepared = (
                    replace(
                        track,
                        audio_path=result.path,
                        duration=result.duration or track.duration,
                        streaming=result.streaming,
                    )
                    if isinstance(result, PreparedAudio)
                    else replace(track, audio_path=result)
                    if isinstance(result, Path)
                    else track
                )
                self._engine.load(deck, prepared, generation=generation)
                if self._link:
                    self._submitted[deck] = prepared
                    self._pin_audio()
                self._set_notice("")
            except ValueError as failure:
                self._set_notice(str(failure))
        self._request_covers()
        self.decksChanged.emit()

    def close(self) -> None:
        self._timer.stop()
        self._jobs.close()
        if self._link:
            self._link.close()
        self._engine.close()

    @Property(str, notify=noticeChanged)
    def notice(self) -> str:
        return self._notice

    def _set_notice(self, notice: str) -> None:
        self._notice = notice
        self.noticeChanged.emit()

    @Property(list, notify=decksChanged)
    def decks(self) -> list[dict[str, str | bool | float]]:
        return [
            dict(
                title=state.track.title if state.track else "Choose a track",
                artist=state.track.artist if state.track else "Load from the library below",
                artwork=self._model.artwork(state.track),
                status=("Preparing audio" if self._link else "Checking file")
                if index in self._preparing
                else state.status.value,
                elapsed=time_label(state.position),
                remaining=time_label(max(0, state.track.duration - state.position))
                if state.track
                else "00:00",
                loadedProgress=max(
                    0.0,
                    min(1.0, state.buffered_duration / state.track.duration),
                )
                if state.track and state.track.duration and state.buffered_duration is not None
                else 1.0
                if state.track and state.status not in (Status.LOADING, Status.WAITING)
                else 0.0,
                downloadMessage=self._download_message(index),
                progress=max(0.0, min(1.0, state.position / state.track.duration))
                if state.track and state.track.duration
                else 0.0,
                canLoad=state.can_change_track,
                canUnload=(state.track is not None or index in self._preparing)
                and state.can_change_track,
                needleDown=state.needle_down,
                platterSpinning=state.platter_spinning,
                playing=state.status == Status.PLAYING,
                error=state.error,
                transportMessage=state.transport_message,
            )
            for index, state in enumerate(self._engine.decks)
        ]

    def _download_message(self, deck: int) -> str:
        if self._link is None:
            return ""
        state = self._engine.decks[deck]
        pending = self._preparing.get(deck)
        track = pending[0] if pending else state.track
        if track is None:
            return ""
        transfer = self._link.streams.state(track)
        if transfer is None:
            return ""
        if transfer.error:
            return transfer.error + " · Only buffered audio is available"
        if transfer.status == "complete":
            if state.status == Status.ERROR:
                return "Downloaded · Audio decoding failed"
            return "Fully downloaded" if state.download_complete else "Downloaded · Decoding audio"
        percentage = int(100 * transfer.received / transfer.total) if transfer.total else 0
        prefix = f"Downloading {track.title}" if pending else "Downloading"
        return f"{prefix} · {percentage}%"

    @Slot(int, str)
    def loadTrack(self, deck: int, track_id: str) -> None:
        self._tick()
        try:
            if deck not in (0, 1):
                raise ValueError("Choose deck A or B")
            if not self._engine.decks[deck].can_change_track:
                raise ValueError(
                    "Stop the record or lift the needle before changing tracks"
                    if self.isSimulation
                    else "Wait for a connected, stopped engine before changing tracks"
                )
            track = self._library.get(track_id)
            # Audio has priority over active and queued optional cover downloads.
            for index in tuple(self._cover_requests):
                self._jobs.cancel(JobKind.for_cover(index))
                self._cover_attempts.pop(index, None)
            self._cover_requests.clear()
            self._cover_attempts.pop(deck, None)
            if not self.isDemo:
                self._preparing[deck] = (track, self._engine.decks[deck].connection_generation)
                self._pin_audio()
                self._pin_covers()
                link = self._link
                self._jobs.submit(
                    JobKind.for_deck(deck),
                    (
                        (lambda event: link.prepare_progressive(track, event))
                        if not self.isSimulation
                        else (lambda event: link.prepare(track, event))
                    )
                    if link
                    else (lambda event: prepare_audio(track)),
                )
            else:
                self._jobs.cancel(JobKind.for_deck(deck))
                self._preparing.pop(deck, None)
                self._engine.load(deck, track)
        except (KeyError, ValueError) as error:
            self._set_notice(str(error))
            return
        self._set_notice("")
        self.decksChanged.emit()

    @Slot(int, bool)
    def setNeedleDown(self, deck: int, down: bool) -> None:
        if not isinstance(self._engine, DemoEngine):
            return
        self._tick()
        self._engine.set_needle(deck, down)
        self._set_notice("")
        self.decksChanged.emit()

    @Slot(int, bool)
    def setPlatterSpinning(self, deck: int, spinning: bool) -> None:
        if not isinstance(self._engine, DemoEngine):
            return
        self._tick()
        self._engine.set_platter(deck, spinning)
        self._set_notice("")
        self.decksChanged.emit()

    @Slot(int)
    def unload(self, deck: int) -> None:
        self._tick()
        try:
            self._engine.unload(deck)
            self._jobs.cancel(JobKind.for_cover(deck))
            self._cover_requests.pop(deck, None)
            self._cover_attempts.pop(deck, None)
            self._jobs.cancel(JobKind.for_deck(deck))
            self._preparing.pop(deck, None)
        except ValueError as error:
            self._set_notice(str(error))
            return
        self._set_notice("")
        self.decksChanged.emit()

    def _pin_covers(self) -> None:
        if self._link:
            tracks = [s.track for s in self._engine.decks if s.track]
            tracks += [t for t, _ in self._preparing.values()] + list(self._submitted.values())
            self._link.covers.protect(
                tuple(
                    Path(QUrl(self._model.artwork(t)).toLocalFile())
                    for t in tracks
                    if self._model.artwork(t)
                )
            )

    def _request_covers(self) -> None:
        link = self._link
        if (
            link is None
            or self._preparing
            or any(s.status in (Status.WAITING, Status.LOADING) for s in self._engine.decks)
        ):
            return
        for deck, state in enumerate(self._engine.decks):
            track = state.track
            if (
                track
                and state.status in (Status.READY, Status.STOPPED, Status.PLAYING, Status.FINISHED)
                and track.artwork_path
                and not self._model.artwork(track)
                and deck not in self._cover_requests
                and self._cover_attempts.get(deck) != (track.id, state.connection_generation)
                and link.available(track)
            ):
                self._cover_requests[deck] = (track, state.connection_generation)
                self._cover_attempts[deck] = (track.id, state.connection_generation)
                self._jobs.submit(JobKind.for_cover(deck), partial(link.cover, track))

    def _pin_audio(self) -> None:
        if self._link:
            for deck, submitted in tuple(self._submitted.items()):
                state = self._engine.decks[deck]
                if (state.track and state.track.audio_path == submitted.audio_path) or (
                    not state.load_pending
                    and state.status not in (Status.MISSING, Status.DISCONNECTED, Status.WAITING)
                    and state.transport_message != "Engine state unavailable"
                ):
                    self._submitted.pop(deck)
            tracks = tuple(s.track for s in self._engine.decks if s.track)
            tracks += tuple(self._submitted.values())
            preparing = tuple(t for t, _ in self._preparing.values())
            self._link.audio.protect(tracks + preparing)
            self._link.streams.protect(
                tracks,
                preparing=tuple(t.id for t in preparing),
                authoritative=all(
                    not s.load_pending
                    and s.status
                    not in (Status.MISSING, Status.DISCONNECTED, Status.WAITING, Status.LOADING)
                    and s.transport_message != "Engine state unavailable"
                    for s in self._engine.decks
                ),
            )

    def _sync_sources(self) -> None:
        link = self._link
        if link is None:
            return
        removed = self._model.forget_evicted_covers(link.covers.paths())
        for deck, (track_id, _) in tuple(self._cover_attempts.items()):
            if track_id in removed:
                self._cover_attempts.pop(deck)
        if removed:
            self.decksChanged.emit()
        for deck, (track, _) in tuple(self._cover_requests.items()):
            if not link.available(track):
                self._jobs.cancel(JobKind.for_cover(deck))
                self._cover_requests.pop(deck)
        for deck, (track, _) in tuple(self._preparing.items()):
            if not link.available(track):
                self._jobs.cancel(JobKind.for_deck(deck))
                self._preparing.pop(deck)
                self._set_notice("USB disconnected; unfinished download cancelled")
                self.decksChanged.emit()
        if self._importing and self._pending_import_generation:
            if link.sources.media(self._pending_import_generation).cancelled.is_set():
                # Preserve the requested source for a new media generation;
                # an explicit Cancel or another selection still abandons it.
                self._jobs.cancel(JobKind.IMPORT)
                self._importing = False
                self.importingChanged.emit()
                self._set_notice("USB disconnected while reading its library; waiting to reconnect")
        status = link.status
        if status != self._link_status:
            self._link_status = status
            self.linkChanged.emit()
        if self._sources_revision != link.sources.revision:
            self._sources_revision = link.sources.revision
            self.sourcesChanged.emit()
            self.importingChanged.emit()
            if self._source_key:
                view = link.sources.view(self._source_key)
                if view.media.cancelled.is_set():
                    base = view.library or self._library
                    self._library = Library(
                        tuple(
                            replace(
                                t,
                                available=False,
                                unavailable_reason=view.error or "USB disconnected",
                            )
                            for t in base.tracks
                        ),
                        base.playlists,
                        name=base.name,
                        source_id=base.source_id,
                        format_name=base.format_name,
                        warnings=base.warnings,
                    )
                    self._refresh_browser()
                    self.libraryChanged.emit()
            if self._requested_source and not self._importing:
                wanted = link.sources.view(self._requested_source)
                if (
                    not wanted.media.cancelled.is_set()
                    and wanted.media.source_id != self._pending_import_generation
                ):
                    self._open_source(self._requested_source)
        self._pin_audio()
        self._pin_covers()

    def _tick(self) -> None:
        self._sync_sources()
        now = monotonic()
        elapsed, self._last_tick = now - self._last_tick, now
        if self._engine.advance(elapsed) or (
            self._link
            and (self._preparing or any(s.track and s.track.streaming for s in self._engine.decks))
        ):
            self.decksChanged.emit()
        self._request_covers()
