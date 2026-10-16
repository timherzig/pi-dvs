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


class Status(StrEnum):
    EMPTY = "Empty"
    LOADING = "Loading"
    READY = "Ready"
    PLAYING = "Playing"
    STOPPED = "Stopped"
    FINISHED = "Finished"
    ERROR = "Unavailable"


@dataclass(frozen=True)
class DeckState:
    track: Track | None = None
    status: Status = Status.EMPTY
    position: float = 0.0
    error: str = ""
    needle_down: bool = False
    platter_spinning: bool = False

    @property
    def can_change_track(self) -> bool:
        """The simulator locks track changes while the needle reads a moving record."""
        return not (self.needle_down and self.platter_spinning)
