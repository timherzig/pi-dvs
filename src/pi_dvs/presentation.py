"""Qt models and user actions. Audio-independent behavior lives in the engine."""

from dataclasses import replace
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
from pi_dvs.model import Status, Track
from pi_dvs.rekordbox import import_library, prepare_audio


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
            artwork_url(track),
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

    def __init__(self, library: Library, engine: Engine, cache: Path | None = None) -> None:
        super().__init__()
        self._library = library
        self._engine = engine
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
        self._browse = library.browse("tracks")
        self._query = ""
        self._notice = ""
        self._model = TrackListModel(self._browse.tracks, self)
        self._last_tick = monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

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
        self._importing = True
        self.importingChanged.emit()
        self._set_notice("")
        self._jobs.submit(
            JobKind.IMPORT,
            lambda event: import_library(
                root,
                self._cache,
                format_choice=format_choice,
                cancelled=event,
            ),
        )

    @Slot()
    def refreshExport(self) -> None:
        if self._source_root:
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
        self._importing = False
        self.importingChanged.emit()

    @Slot(object, object, str)
    def _completed(self, operation: JobKind, result: object, error: str) -> None:
        deck = operation.deck
        if deck is None:
            self._importing = False
            self.importingChanged.emit()
            if isinstance(result, Library):
                self._library = result
                if self._pending_source:
                    self._source_root, self._format_choice = self._pending_source
                self.browseCategory("tracks")
                self.libraryChanged.emit()
                self._set_notice(" ".join(result.warnings))
            else:
                self._set_notice(error)
            return
        pending = self._preparing.pop(deck, None)
        if error:
            self._set_notice(f"Cannot load audio: {error}")
        elif pending:
            track, generation = pending
            try:
                self._engine.load(
                    deck,
                    replace(track, audio_path=result) if isinstance(result, Path) else track,
                    generation=generation,
                )
                self._set_notice("")
            except ValueError as failure:
                self._set_notice(str(failure))
        self.decksChanged.emit()

    def close(self) -> None:
        self._timer.stop()
        self._jobs.close()
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
                artwork=artwork_url(state.track),
                status="Checking file" if index in self._preparing else state.status.value,
                elapsed=time_label(state.position),
                remaining=time_label(max(0, state.track.duration - state.position))
                if state.track
                else "00:00",
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
            if not self.isDemo:
                self._preparing[deck] = (track, self._engine.decks[deck].connection_generation)
                self._jobs.submit(JobKind.for_deck(deck), lambda event: prepare_audio(track))
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
            self._jobs.cancel(JobKind.for_deck(deck))
            self._preparing.pop(deck, None)
        except ValueError as error:
            self._set_notice(str(error))
            return
        self._set_notice("")
        self.decksChanged.emit()

    def _tick(self) -> None:
        now = monotonic()
        elapsed, self._last_tick = now - self._last_tick, now
        if self._engine.advance(elapsed):
            self.decksChanged.emit()
