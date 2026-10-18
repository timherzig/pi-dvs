"""Reader-neutral records: paths are relative to the exported media, never the host."""

from dataclasses import dataclass

from pi_dvs.model import Playlist


@dataclass(frozen=True)
class ExportTrack:
    id: str
    title: str
    artist: str
    duration: float
    path: str
    artwork: str = ""
    album: str = ""
    genre: str = ""
    key: str = ""
    bpm: float = 0.0


@dataclass(frozen=True)
class Export:
    tracks: tuple[ExportTrack, ...]
    playlists: tuple[Playlist, ...]


class ImportFailure(ValueError):
    """An export cannot safely be used; the previous catalog must stay active."""


class ImportCancelled(Exception):
    """A newer selection superseded this import."""
