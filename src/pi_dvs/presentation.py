"""Qt models and user actions. Audio-independent behavior lives in the engine."""

from time import monotonic

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
    QTimer,
    Signal,
    Slot,
)

from pi_dvs.engine import DemoEngine
from pi_dvs.library import Library
from pi_dvs.model import Status, Track


def time_label(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes:02}:{seconds:02}"


def artwork_url(track: Track | None) -> str:
    if track and track.artwork and track.artwork.is_file():
        return track.artwork.as_uri()
    return ""


class TrackListModel(QAbstractListModel):
    _roles = ("trackId", "trackTitle", "artist", "duration", "artwork", "available")

    def __init__(self, tracks: tuple[Track, ...], parent: QObject) -> None:
        super().__init__(parent)
        self._tracks = tracks

    def roleNames(self) -> dict[int, bytes]:
        return {
            int(Qt.ItemDataRole.UserRole) + i: name.encode() for i, name in enumerate(self._roles)
        }

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._tracks)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
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

    def __init__(self, library: Library, engine: DemoEngine) -> None:
        super().__init__()
        self._library = library
        self._engine = engine
        self._query = ""
        self._notice = ""
        self._model = TrackListModel(library.tracks, self)
        self._last_tick = monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @Property(QObject, constant=True)
    def libraryModel(self):
        return self._model

    @Property(int, notify=searchChanged)
    def trackCount(self) -> int:
        return self._model.rowCount()

    @Property(int, constant=True)
    def totalTracks(self) -> int:
        return len(self._library.tracks)

    @Property(str, notify=searchChanged)
    def query(self) -> str:
        return self._query

    @query.setter
    def query(self, value: str) -> None:
        if value != self._query:
            self._query = value
            self._model.replace_tracks(self._library.search(value))
            self.searchChanged.emit()

    @Property(str, notify=noticeChanged)
    def notice(self) -> str:
        return self._notice

    def _set_notice(self, notice: str) -> None:
        self._notice = notice
        self.noticeChanged.emit()

    @Property("QVariantList", notify=decksChanged)
    def decks(self) -> list[dict]:
        return [
            dict(
                title=state.track.title if state.track else "Choose a track",
                artist=state.track.artist if state.track else "Load from the library below",
                artwork=artwork_url(state.track),
                status=state.status.value,
                elapsed=time_label(state.position),
                remaining=time_label(max(0, state.track.duration - state.position))
                if state.track
                else "00:00",
                progress=state.position / state.track.duration
                if state.track and state.track.duration
                else 0.0,
                canPlay=state.status in (Status.READY, Status.PLAYING, Status.PAUSED),
                canLoad=state.status != Status.PLAYING,
                canUnload=state.track is not None and state.status != Status.PLAYING,
                playing=state.status == Status.PLAYING,
                error=state.error,
            )
            for state in self._engine.decks
        ]

    @Slot(int, str)
    def loadTrack(self, deck: int, track_id: str) -> None:
        try:
            self._engine.load(deck, self._library.get(track_id))
        except (KeyError, ValueError) as error:
            self._set_notice(str(error))
            return
        self._set_notice("")
        self.decksChanged.emit()

    @Slot(int)
    def togglePlayback(self, deck: int) -> None:
        self._tick()
        self._engine.toggle(deck)
        self.decksChanged.emit()

    @Slot(int)
    def unload(self, deck: int) -> None:
        try:
            self._engine.unload(deck)
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
