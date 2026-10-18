"""Bound and validate DeviceSQL before using the pinned, read-only PDB parser."""

import struct
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from rekordbox_pdb import Database  # type: ignore[import-untyped]
from rekordbox_pdb.pdb import decode_string  # type: ignore[import-untyped]

from pi_dvs.model import Playlist
from pi_dvs.rekordbox.records import Export, ExportTrack, ImportFailure


def _page_row_offsets(page: bytes) -> list[int]:
    """Validate and read live offsets using DeviceSQL's 13-bit allocated-slot count."""
    if page[27] & 0x40:
        return []
    # The next 11 bits count live rows, not allocated offsets. Deleted slots
    # remain in the directory. See Deep Symmetry's Table Page Header analysis.
    count = struct.unpack_from("<H", page, 24)[0] & 0x1FFF
    heap_end = len(page) - ((count + 15) // 16) * 36
    if heap_end < 40:
        raise ImportFailure("Invalid PDB row directory")
    offsets = []
    for row in range(count):
        base = len(page) - (row // 16) * 36
        present = struct.unpack_from("<H", page, base - 4)[0]
        if present & (1 << (row % 16)):
            offset = 40 + struct.unpack_from("<H", page, base - 6 - 2 * (row % 16))[0]
            if not 40 <= offset < heap_end:
                raise ImportFailure("PDB row points outside its data heap")
            offsets.append(offset)
    return offsets


def validate_pages(data: bytes) -> None:
    """Reject truncated pages and cycles (the upstream parser follows links unbounded)."""
    if len(data) < 28 or data[:4] != bytes(4):
        raise ImportFailure("Not a Device Library PDB export")
    page_size, tables = struct.unpack_from("<II", data, 4)
    if not 512 <= page_size <= 65536 or len(data) % page_size:
        raise ImportFailure("Invalid PDB page size or truncated export")
    if not 1 <= tables <= (page_size - 28) // 16:
        raise ImportFailure("Invalid PDB table directory")
    table_types: set[int] = set()
    for i in range(tables):
        kind, _, first, last = struct.unpack_from("<4I", data, 28 + 16 * i)
        if kind in table_types:
            raise ImportFailure("Duplicate PDB table")
        table_types.add(kind)
        visited: set[int] = set()
        page = first
        while True:
            if page in visited or not 0 < page < len(data) // page_size:
                raise ImportFailure("Broken or cyclic PDB page chain")
            visited.add(page)
            start = page * page_size
            index, page_kind, following = struct.unpack_from("<3I", data, start + 4)
            if index != page or page_kind != kind:
                raise ImportFailure("PDB page does not belong to its table")
            _page_row_offsets(data[start : start + page_size])
            if page == last:
                break
            page = following
    if 0 not in table_types:
        raise ImportFailure("PDB has no track table")


@dataclass(frozen=True)
class _Album:
    id: int
    name: str


def _album(page: bytes, row: int) -> _Album:
    # Upstream 0.1.0 handles only the near-name variant. DeviceSQL also has
    # subtype 0x84 with a 16-bit name offset (Deep Symmetry's Album Rows).
    subtype = struct.unpack_from("<H", page, row)[0]
    offset = struct.unpack_from("<H", page, row + 22)[0] if subtype == 0x84 else page[row + 21]
    return _Album(
        struct.unpack_from("<I", page, row + 12)[0], str(decode_string(page, row + offset))
    )


class _Database(Database):  # type: ignore[misc]  # upstream does not publish py.typed
    _row_parsers = {
        kind: parser
        for kind, parser in cast(
            dict[int, Callable[[bytes, int], object]], Database._row_parsers
        ).items()
        if kind in (0, 1, 2, 3, 5, 7, 8, 13)
    }
    _row_parsers[3] = _album

    def _row_offsets(self, page: bytes) -> list[int]:
        # The pinned upstream reader truncates the allocated-slot count to 9 bits.
        # Use the same full-width decoder for parsing and structural preflight.
        return _page_row_offsets(page)


def read_pdb(data: bytes) -> Export:
    try:
        validate_pages(data)
        db = _Database(data)
        artists: dict[int, str] = {a.id: a.name for a in db.artists}
        albums: dict[int, str] = {a.id: a.name for a in db.albums}
        genres: dict[int, str] = {a.id: a.name for a in db.genres}
        keys: dict[int, str] = {a.id: a.name for a in db.keys}
        art: dict[int, str] = {a.id: a.path for a in db.artwork}
        tracks = tuple(
            ExportTrack(
                id=str(t.id),
                title=str(t.title),
                artist=artists.get(t.artist_id, ""),
                duration=float(t.duration),
                path=str(t.file_path),
                artwork=art.get(t.artwork_id, ""),
                album=albums.get(t.album_id, ""),
                genre=genres.get(t.genre_id, ""),
                key=keys.get(t.key_id, ""),
                bpm=float(t.tempo) / 100,
            )
            for t in db.tracks
        )
        entries: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for entry in db.playlist_entries:
            entries[entry.playlist_id].append((entry.entry_index, str(entry.track_id)))
        playlists = tuple(
            Playlist(
                id=str(p.id),
                name=str(p.name),
                parent_id=str(p.parent_id) if p.parent_id else "",
                is_folder=bool(p.is_folder),
                order=int(p.sort_order),
                track_ids=tuple(tid for _, tid in sorted(entries[p.id])),
            )
            for p in db.playlist_tree
        )
        return Export(tracks, playlists)
    except (IndexError, struct.error, UnicodeError, ValueError) as error:
        raise ImportFailure(
            f"Cannot read Device Library: {error}. Re-export it in rekordbox."
        ) from error
