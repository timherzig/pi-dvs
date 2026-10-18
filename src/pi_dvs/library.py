"""Read the bundled demo catalog and search track metadata."""

import json
import unicodedata
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from pi_dvs.model import Playlist, Track


def _search_text(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


class Library:
    def __init__(
        self,
        tracks: tuple[Track, ...],
        playlists: tuple[Playlist, ...] = (),
        *,
        name: str = "Demo library",
        source_id: str = "demo",
        format_name: str = "Demo",
        warnings: tuple[str, ...] = (),
    ) -> None:
        self.tracks = tracks
        self.playlists = playlists
        self.name = name
        self.source_id = source_id
        self.format_name = format_name
        self.warnings = warnings
        self._playlists = {p.id: p for p in playlists}
        if len(self._playlists) != len(playlists):
            raise ValueError("Playlist IDs must be unique")
        for playlist in playlists:
            seen = {playlist.id}
            parent = playlist.parent_id
            while parent:
                if parent in seen or parent not in self._playlists:
                    raise ValueError("Invalid playlist folder hierarchy")
                seen.add(parent)
                folder = self._playlists[parent]
                if not folder.is_folder:
                    raise ValueError("Playlist parent must be a folder")
                parent = folder.parent_id
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

    def browse(self, category: str, selection: str = "", query: str = "") -> "BrowseResult":
        if category == "tracks":
            return BrowseResult(
                "All tracks",
                tracks=tuple(
                    sorted(
                        self.search(query),
                        key=lambda t: (_search_text(t.title), _search_text(t.artist), t.id),
                    )
                ),
                is_tracks=True,
            )
        if category == "playlists":
            playlist = self._playlists.get(selection)
            if selection and playlist is None:
                raise ValueError("Playlist no longer exists")
            if playlist and not playlist.is_folder:
                matches = {t.id for t in self.search(query)}
                tracks = tuple(self._by_id[i] for i in playlist.track_ids if i in matches)
                return BrowseResult(playlist.name, tracks=tracks, is_tracks=True)
            entries = tuple(
                BrowseEntry(p.id, p.name, "Folder" if p.is_folder else f"{len(p.track_ids)} tracks")
                for p in sorted(self.playlists, key=lambda p: (p.order, p.name.casefold(), p.id))
                if p.parent_id == selection and _search_text(query) in _search_text(p.name)
            )
            return BrowseResult(playlist.name if playlist else "Playlists", entries=entries)
        fields = {"artists": "artist", "albums": "album", "genres": "genre", "keys": "key"}
        if category not in (*fields, "bpm"):
            raise ValueError("Unknown browse category")

        def group(track: Track) -> str:
            if category == "bpm":
                if not track.bpm:
                    return "Unknown"
                lower = int(track.bpm // 5) * 5
                return f"{lower:03d}–{lower + 4:03d} BPM"
            return str(getattr(track, fields[category])) or "Unknown"

        if selection:
            return BrowseResult(
                selection,
                tracks=tuple(t for t in self.search(query) if group(t) == selection),
                is_tracks=True,
            )
        counts: dict[str, int] = {}
        for track in self.tracks:
            value = group(track)
            counts[value] = counts.get(value, 0) + 1
        entries = tuple(
            BrowseEntry(value, value, f"{counts[value]} tracks")
            for value in sorted(counts, key=_search_text)
            if _search_text(query) in _search_text(value)
        )
        return BrowseResult(category.title(), entries=entries)

    def get(self, track_id: str) -> Track:
        return self._by_id[track_id]


@dataclass(frozen=True)
class BrowseEntry:
    id: str
    name: str
    detail: str


@dataclass(frozen=True)
class BrowseResult:
    title: str
    entries: tuple[BrowseEntry, ...] = ()
    tracks: tuple[Track, ...] = ()
    is_tracks: bool = False


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
