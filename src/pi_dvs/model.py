"""Application values with no GUI or audio dependencies."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    duration: float
    artwork: Path | None = None
    available: bool = True
    audio_path: Path | None = None
    source_id: str = "demo"
    export_id: str = ""
    relative_path: str = ""
    media_root: Path | None = None
    album: str = ""
    genre: str = ""
    key: str = ""
    bpm: float = 0.0
    analysis_path: str = ""
    artwork_path: str = ""
    sample_rate: int = 0
    bitrate: int = 0
    bit_depth: int = 0
    unavailable_reason: str = ""
    streaming: bool = False


@dataclass(frozen=True)
class Playlist:
    id: str
    name: str
    parent_id: str = ""
    is_folder: bool = False
    order: int = 0
    track_ids: tuple[str, ...] = ()


class Status(StrEnum):
    MISSING = "Engine missing"
    DISCONNECTED = "Disconnected"
    WAITING = "Waiting for engine"
    EMPTY = "Empty"
    LOADING = "Loading"
    READY = "Ready"
    PLAYING = "Playing"
    STOPPED = "Stopped"
    FINISHED = "Finished"
    ERROR = "Unavailable"
    BUFFERING = "Buffering"


@dataclass(frozen=True)
class DeckState:
    track: Track | None = None
    status: Status = Status.EMPTY
    position: float = 0.0
    error: str = ""
    needle_down: bool = False
    platter_spinning: bool = False
    change_allowed: bool | None = None
    transport_message: str = ""
    connection_generation: int = 0
    buffered_duration: float | None = None
    download_complete: bool = True
    load_pending: bool = False

    @property
    def can_change_track(self) -> bool:
        """The simulator locks track changes while the needle reads a moving record."""
        if self.change_allowed is not None:
            return self.change_allowed
        return not (self.needle_down and self.platter_spinning)
