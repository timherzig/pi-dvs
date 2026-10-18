"""Read the encrypted OneLibrary export through SQLCipher, with no write access."""

import sqlite3
from pathlib import Path
from threading import Event
from typing import cast

from sqlcipher3 import dbapi2 as sqlcipher  # type: ignore[import-untyped]

from pi_dvs.model import Playlist
from pi_dvs.rekordbox.records import Export, ExportTrack, ImportCancelled, ImportFailure

# Public interoperability key, shared by exported OneLibrary databases. This is
# not the user's desktop master.db key. Source: pyrekordbox (MIT); see notices.
EXPORT_KEY = "r8gddnr4k847830ar6cqzbkk0el6qytmb3trbbx805jm74vez64i5o8fnrqryqls"


def read_onelibrary(path: Path, cancelled: Event) -> Export:
    # SQLCipher implements Python's sqlite3 DB-API. The cast supplies the missing
    # third-party typing, not a runtime conversion. URI ro + query_only enforce it.
    connection = cast(
        sqlite3.Connection,
        sqlcipher.connect(
            path.as_uri() + "?mode=ro&immutable=1",
            uri=True,
        ),
    )
    try:
        connection.execute(f"PRAGMA key = '{EXPORT_KEY}'")
        connection.execute("PRAGMA query_only = ON")
        connection.set_progress_handler(lambda: int(cancelled.is_set()), 1000)
        tracks = tuple(
            ExportTrack(
                id=str(row[0]),
                title=str(row[1] or ""),
                artist=str(row[2] or ""),
                duration=float(row[3] or 0),
                path=str(row[4] or ""),
                artwork=str(row[5] or ""),
                album=str(row[6] or ""),
                genre=str(row[7] or ""),
                key=str(row[8] or ""),
                bpm=float(row[9] or 0) / 100,
            )
            for row in connection.execute("""
            SELECT c.content_id, c.title, a.name, c.length, c.path, i.path,
                   al.name, g.name, k.name, c.bpmx100
            FROM content c
            LEFT JOIN artist a ON a.artist_id = c.artist_id_artist
            LEFT JOIN album al ON al.album_id = c.album_id
            LEFT JOIN genre g ON g.genre_id = c.genre_id
            LEFT JOIN "key" k ON k.key_id = c.key_id
            LEFT JOIN image i ON i.image_id = c.image_id
            ORDER BY c.content_id
        """)
        )
        entries: dict[str, list[str]] = {}
        for pid, tid, _ in connection.execute(
            "SELECT playlist_id, content_id, sequenceNo FROM playlist_content ORDER BY sequenceNo"
        ):
            entries.setdefault(str(pid), []).append(str(tid))
        playlists = []
        for pid, name, parent, attribute, order in connection.execute(
            "SELECT playlist_id, name, playlist_id_parent, attribute, sequenceNo FROM playlist"
        ):
            if attribute not in (0, 1):
                raise ImportFailure(f"Unsupported OneLibrary playlist type: {attribute}")
            playlists.append(
                Playlist(
                    str(pid),
                    str(name or "Untitled"),
                    str(parent) if parent else "",
                    bool(attribute),
                    int(order or 0),
                    tuple(entries.get(str(pid), ())),
                )
            )
        return Export(tracks, tuple(playlists))
    except (sqlcipher.DatabaseError, ValueError, TypeError) as error:
        if cancelled.is_set():
            raise ImportCancelled() from error
        raise ImportFailure(
            "Cannot read OneLibrary: unsupported schema or corrupt/encrypted export. "
            "Re-export the USB in rekordbox."
        ) from error
    finally:
        connection.close()
