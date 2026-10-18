"""Rebuild synthetic, redistributable DeviceSQL and encrypted OneLibrary fixtures.

The PDB encoder is independent of the production parser. Its layouts follow
Deep Symmetry's format specification. No personal exports or commercial audio
are used. Run with the project's Python from the repository root.
"""

import math
import sqlite3
import struct
import wave
import zlib
from pathlib import Path
from typing import cast

from sqlcipher3 import dbapi2 as sql  # type: ignore[import-untyped]  # no third-party stubs

KEY = "r8gddnr4k847830ar6cqzbkk0el6qytmb3trbbx805jm74vez64i5o8fnrqryqls"
AUDIO = "/Contents/Élise/Café 東京.wav"
ART = "/PIONEER/Artwork/cover.png"
ALBUM = "A distant album " + "a" * 140


def string(value: str) -> bytes:
    if value.isascii() and len(value) < 126:
        return bytes([(len(value) + 1) * 2 + 1]) + value.encode("ascii")
    encoding, tag = ("ascii", 0x40) if value.isascii() else ("utf-16-le", 0x90)
    data = value.encode(encoding)
    return bytes([tag]) + struct.pack("<H", len(data) + 4) + b"\0" + data


def track(tid: int, title: str, path: str) -> bytes:
    row = bytearray(136)
    struct.pack_into("<H", row, 0, 0x24)
    for offset, value in {
        8: 44100,
        16: 8864,
        28: 1,
        32: 1,
        48: 1411,
        56: 12850,
        60: 1,
        64: 1,
        68: 1,
        72: tid,
    }.items():
        struct.pack_into("<I", row, offset, value)
    struct.pack_into("<H", row, 84, 1)
    for i in range(21):
        text = {17: title, 19: path.rsplit("/", 1)[-1], 20: path}.get(i, "")
        struct.pack_into("<H", row, 94 + 2 * i, len(row))
        row.extend(string(text))
    return bytes(row)


def artist() -> bytes:
    # Exercise the far-name variant independently from the album variant.
    row = bytearray(300)
    struct.pack_into("<H", row, 0, 0x64)
    struct.pack_into("<I", row, 4, 1)
    struct.pack_into("<H", row, 10, 300)
    return bytes(row) + string("Élise")


def album() -> bytes:
    row = bytearray(300)
    struct.pack_into("<H", row, 0, 0x84)
    struct.pack_into("<I", row, 12, 1)
    struct.pack_into("<H", row, 22, 300)
    return bytes(row) + string(ALBUM)


def playlist(pid: int, parent: int, order: int, name: str, folder: bool) -> bytes:
    return struct.pack("<5I", parent, 0, order, pid, int(folder)) + string(name)


def pdb_bytes(*, entries: list[int] | None = None, deleted: bool = False) -> bytes:
    tables: dict[int, list[bytes]] = {
        0: [
            track(1, "Café 東京", AUDIO),
            track(2, "Missing", "/Contents/Lost.wav"),
            track(3, "Unsupported", "/Contents/Track.xyz"),
        ],
        1: [struct.pack("<I", 1) + string("House")],
        2: [artist()],
        3: [album()],
        5: [struct.pack("<2I", 1, 0) + string("Am")],
        7: [
            playlist(10, 0, 0, "Sets", True),
            playlist(11, 10, 0, "Warm-up", True),
            playlist(12, 11, 0, "Café set", False),
            playlist(13, 10, 1, "Empty", False),
        ],
        8: [struct.pack("<3I", i, tid, 12) for i, tid in enumerate(entries or [2, 1, 1, 999])],
        13: [struct.pack("<I", 1) + string(ART)],
    }
    pages = [bytearray(4096)]
    struct.pack_into("<7I", pages[0], 0, 0, 4096, len(tables), len(tables) + 1, 0, 1, 0)
    for number, (kind, rows) in enumerate(tables.items(), 1):
        struct.pack_into("<4I", pages[0], 28 + (number - 1) * 16, kind, 0, number, number)
        page = bytearray(4096)
        struct.pack_into("<3I", page, 4, number, kind, 0)
        live_rows = len(rows) - int(deleted and kind == 0)
        page[24:27] = (len(rows) | (live_rows << 13)).to_bytes(3, "little")
        page[27] = 0x34 if deleted and kind == 0 else 0x24
        heap = 40
        for i, row in enumerate(rows):
            base = 4096 - (i // 16) * 36
            assert heap + len(row) < 4096 - ((len(rows) + 15) // 16) * 36
            struct.pack_into("<H", page, base - 6 - (i % 16) * 2, heap - 40)
            flags = struct.unpack_from("<H", page, base - 4)[0]
            if not (deleted and kind == 0 and i == 2):
                flags |= 1 << (i % 16)
            struct.pack_into("<H", page, base - 4, flags)
            page[heap : heap + len(row)] = row
            heap += len(row)
        pages.append(page)
    return b"".join(pages)


def build(root: Path) -> None:
    export = root / "PIONEER/rekordbox"
    export.mkdir(parents=True, exist_ok=True)
    (export / "export.pdb").write_bytes(pdb_bytes())
    db_path = export / "exportLibrary.db"
    db_path.unlink(missing_ok=True)
    # SQLCipher implements the sqlite3 DB-API; the cast supplies missing stubs.
    con = cast(sqlite3.Connection, sql.connect(str(db_path)))
    con.execute(f"PRAGMA key='{KEY}'")
    con.executescript("""
        CREATE TABLE content (content_id INTEGER PRIMARY KEY, title varchar,
          artist_id_artist INTEGER, length INTEGER, path varchar, image_id INTEGER,
          album_id INTEGER, genre_id INTEGER, key_id INTEGER, bpmx100 INTEGER);
        CREATE TABLE artist (artist_id INTEGER PRIMARY KEY, name varchar);
        CREATE TABLE album (album_id INTEGER PRIMARY KEY, name varchar);
        CREATE TABLE genre (genre_id INTEGER PRIMARY KEY, name varchar);
        CREATE TABLE "key" (key_id INTEGER PRIMARY KEY, name varchar);
        CREATE TABLE image (image_id INTEGER PRIMARY KEY, path varchar);
        CREATE TABLE playlist (playlist_id INTEGER PRIMARY KEY, name varchar,
          playlist_id_parent INTEGER, attribute INTEGER, sequenceNo INTEGER);
        CREATE TABLE playlist_content (playlist_id INTEGER, content_id INTEGER, sequenceNo INTEGER);
    """)
    for tid, title, path in [
        (1, "Café 東京", AUDIO),
        (2, "Missing", "/Contents/Lost.wav"),
        (3, "Unsupported", "/Contents/Track.xyz"),
    ]:
        con.execute("INSERT INTO content VALUES (?,?,1,1,?,1,1,1,1,12850)", (tid, title, path))
    for table, name in [
        ("artist", "Élise"),
        ("album", ALBUM),
        ("genre", "House"),
        ("key", "Am"),
        ("image", ART),
    ]:
        con.execute(f'INSERT INTO "{table}" VALUES (1,?)', (name,))
    con.executemany(
        "INSERT INTO playlist VALUES (?,?,?,?,?)",
        [
            (10, "Sets", 0, 1, 0),
            (11, "Warm-up", 10, 1, 0),
            (12, "Café set", 11, 0, 0),
            (13, "Empty", 10, 0, 1),
        ],
    )
    con.executemany(
        "INSERT INTO playlist_content VALUES (12,?,?)", [(2, 0), (1, 1), (1, 2), (999, 3)]
    )
    con.commit()
    con.close()
    audio = root / AUDIO.lstrip("/")
    audio.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        wav.writeframes(
            b"".join(
                struct.pack("<hh", *(2 * [int(2000 * math.sin(i * 440 * 2 * math.pi / 44100))]))
                for i in range(44100)
            )
        )
    art = root / ART.lstrip("/")
    art.parent.mkdir(parents=True, exist_ok=True)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    art.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0" + b"\xee\xae\x75" * 2 + b"\0" + b"\x93\xc9\xc7" * 2))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    build(Path(__file__).parent / "usb")
