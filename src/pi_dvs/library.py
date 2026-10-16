"""Read the bundled demo catalog and search track metadata."""

import json
import unicodedata
from importlib.resources import files
from pathlib import Path

from pi_dvs.model import Track


def _search_text(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


class Library:
    def __init__(self, tracks: tuple[Track, ...]) -> None:
        self.tracks = tracks
        self._by_id = {track.id: track for track in tracks}
        if len(self._by_id) != len(tracks):
            raise ValueError("Track IDs must be unique")
        self._searchable = {
            track.id: _search_text(f"{track.title} {track.artist}") for track in tracks
        }

    def search(self, query: str) -> tuple[Track, ...]:
        words = _search_text(query).split()
        return tuple(
            track
            for track in self.tracks
            if all(word in self._searchable[track.id] for word in words)
        )

    def get(self, track_id: str) -> Track:
        return self._by_id[track_id]


def demo_library() -> Library:
    data = files("pi_dvs").joinpath("data")
    rows = json.loads(data.joinpath("tracks.json").read_text(encoding="utf-8"))
    return Library(
        tuple(
            Track(
                id=row["id"],
                title=row["title"],
                artist=row["artist"],
                duration=row["duration"],
                artwork=Path(str(data.joinpath(row["artwork"]))) if row.get("artwork") else None,
                available=row.get("available", True),
            )
            for row in rows
        )
    )
