"""Integration tests against binary DeviceSQL and encrypted OneLibrary exports."""

import hashlib
import shutil
import struct
import wave
from pathlib import Path
from threading import Event

import pytest
from fixtures.build_exports import ALBUM, ART, AUDIO, pdb_bytes
from PIL import Image

from pi_dvs.library import Library
from pi_dvs.model import Playlist, Track
from pi_dvs.rekordbox import import_library, media_path, prepare_audio
from pi_dvs.rekordbox.onelibrary import read_onelibrary
from pi_dvs.rekordbox.pdb import read_pdb
from pi_dvs.rekordbox.records import ImportCancelled, ImportFailure

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def usb(tmp_path):
    return Path(shutil.copytree(FIXTURES / "usb", tmp_path / "USB with spaces"))


def snapshot(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("kind", ["pdb", "onelibrary"])
def test_read_only_import_paths_artwork_metadata_and_playlist_order(usb, tmp_path, kind):
    before = snapshot(usb)
    cache = tmp_path / "local cache"
    library = import_library(usb, cache, format_choice=kind)
    assert len(library.tracks) == 3
    assert len(library.playlists) == 4
    (track,) = library.search("cafe elise")
    assert track.title == "Café 東京"
    assert (track.duration, track.bpm, track.key, track.genre, track.album) == (
        1,
        128.5,
        "Am",
        "House",
        ALBUM,
    )
    assert track.audio_path == usb / AUDIO.lstrip("/")
    assert track.artwork.is_relative_to(cache)
    assert track.artwork.read_bytes() == (usb / ART.lstrip("/")).read_bytes()
    assert prepare_audio(track) == track.audio_path
    with wave.open(str(track.audio_path), "rb") as wav:
        assert wav.getframerate() == 44100
        assert len(wav.readframes(wav.getnframes())) == 44100 * 4
    assert not library.search("missing")[0].available
    assert "missing" in library.search("missing")[0].unavailable_reason
    assert "Unsupported" in library.search("unsupported")[0].unavailable_reason
    playlist = library.browse("playlists", "12")
    assert [t.export_id for t in playlist.tracks] == ["2", "1", "1"]
    assert any("absent" in warning for warning in library.warnings)
    assert [e.name for e in library.browse("playlists").entries] == ["Sets"]
    assert [e.name for e in library.browse("playlists", "10").entries] == ["Warm-up", "Empty"]
    assert library.browse("playlists", "13").is_tracks
    assert library.browse("playlists", "13").tracks == ()
    assert snapshot(usb) == before
    assert len(import_library(usb, cache, format_choice=kind).tracks) == 3


def test_genuine_export_from_independent_upstream():
    export = read_pdb((FIXTURES / "upstream/one-song-export.pdb").read_bytes())
    (track,) = export.tracks
    assert (track.title, track.artist, track.album) == (
        "Super Smash Bros.",
        "BABY GRAVY/Yung Gravy/bbno$",
        "Baby Gravy 3",
    )
    assert (track.duration, track.bpm, track.key) == (153, 146, "Em")
    assert len(export.playlists) == 1


def test_onelibrary_is_encrypted_real_format():
    database = FIXTURES / "usb/PIONEER/rekordbox/exportLibrary.db"
    assert not database.read_bytes().startswith(b"SQLite format 3")
    assert read_onelibrary(database.resolve(), Event()).tracks[0].duration == 1


@pytest.mark.parametrize("kind", ["pdb", "onelibrary"])
def test_readonly_source_relocation_and_identity(usb, tmp_path, kind):
    cache = tmp_path / "cache"
    first = import_library(usb, cache, format_choice=kind)
    moved = usb.rename(tmp_path / "Different volume 東京")
    paths = list(moved.rglob("*"))
    try:
        for path in paths:
            path.chmod(0o555 if path.is_dir() else 0o444)
        second = import_library(moved, cache, format_choice=kind)
        assert second.tracks[0].id != first.tracks[0].id
        assert second.tracks[0].relative_path == first.tracks[0].relative_path
        assert prepare_audio(second.tracks[0]).is_relative_to(moved)
    finally:
        for path in paths:
            path.chmod(0o755 if path.is_dir() else 0o644)


def test_dual_format_precedence_and_visible_fallback(usb, tmp_path):
    assert import_library(usb, tmp_path / "cache").format_name == "Device Library"
    pdb = usb / "PIONEER/rekordbox/export.pdb"
    pdb.write_bytes(b"broken")
    fallback = import_library(usb, tmp_path / "cache")
    assert fallback.format_name == "OneLibrary"
    assert "Device Library" in fallback.warnings[0]
    with pytest.raises(ImportFailure, match="Device Library"):
        import_library(usb, tmp_path / "cache", format_choice="pdb")
    pdb.unlink()
    assert import_library(usb, tmp_path / "cache").format_name == "OneLibrary"
    (usb / "PIONEER/rekordbox/exportLibrary.db").write_bytes(b"not encrypted sqlite")
    with pytest.raises(ImportFailure, match="Re-export"):
        import_library(usb, tmp_path / "cache")


def test_unsupported_directory_configuration_and_cancel(usb, tmp_path):
    with pytest.raises(ImportFailure, match="USB root"):
        import_library(tmp_path / "empty", tmp_path / "cache")
    with pytest.raises(ImportFailure, match="outside"):
        import_library(usb, usb / "cache")
    with pytest.raises(ImportFailure, match="Choose Auto"):
        import_library(usb, tmp_path / "cache", format_choice="xml")
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ImportCancelled):
        import_library(usb, tmp_path / "cache", cancelled=cancelled)


@pytest.mark.parametrize(
    "path", ["", "../outside.mp3", "/Contents/../../secret", "C:\\Music\\x.mp3", "bad\0path"]
)
def test_invalid_export_paths_are_rejected(tmp_path, path):
    with pytest.raises(ImportFailure):
        media_path(tmp_path, path)


def test_paths_and_symlinks_cannot_escape_usb(tmp_path, usb):
    assert media_path(usb, AUDIO.replace("/", "\\")) == usb / AUDIO.lstrip("/")
    (usb / "escape").symlink_to(tmp_path)
    with pytest.raises(ImportFailure, match="escapes"):
        media_path(usb, "/escape/secret.wav")


def test_missing_invalid_and_high_resolution_artwork(usb, tmp_path):
    original = usb / ART.lstrip("/")
    high = original.with_stem("cover_m")
    high.write_bytes(original.read_bytes())
    imported = import_library(usb, tmp_path / "cache")
    assert imported.tracks[0].artwork
    high.write_bytes(b"not an image")
    assert import_library(usb, tmp_path / "cache").tracks[0].artwork
    original.unlink()
    assert import_library(usb, tmp_path / "cache").tracks[0].artwork is None
    high.unlink()
    assert import_library(usb, tmp_path / "cache").tracks[0].artwork is None


def test_load_rechecks_removed_or_emptied_audio(usb, tmp_path):
    track = import_library(usb, tmp_path / "cache").tracks[0]
    track.audio_path.write_bytes(b"")
    with pytest.raises(ImportFailure, match="empty"):
        prepare_audio(track)
    empty = import_library(usb, tmp_path / "cache").tracks[0]
    assert not empty.available
    with pytest.raises(ImportFailure):
        prepare_audio(empty)
    track.audio_path.unlink()
    with pytest.raises(OSError):
        prepare_audio(track)
    with pytest.raises(ImportFailure, match="No audio"):
        prepare_audio(Track("demo", "Title", "Artist", 1))


def test_pdb_deleted_rows_and_more_than_255_playlist_slots():
    assert len(read_pdb(pdb_bytes(deleted=True)).tracks) == 2
    export = read_pdb(pdb_bytes(entries=[1] * 260))
    assert len(next(p for p in export.playlists if p.id == "12").track_ids) == 260


@pytest.mark.parametrize(
    "mutation", ["short", "size", "tables", "duplicate", "cycle", "outside", "wrong_type", "row"]
)
def test_corrupt_pdb_is_bounded_and_actionable(mutation):
    data = bytearray(pdb_bytes())
    if mutation == "short":
        data = data[:20]
    elif mutation == "size":
        struct.pack_into("<I", data, 4, 7)
    elif mutation == "tables":
        struct.pack_into("<I", data, 8, 0xFFFFFFFF)
    elif mutation == "duplicate":
        struct.pack_into("<I", data, 44, 0)
    elif mutation == "cycle":
        struct.pack_into("<I", data, 40, 2)
        struct.pack_into("<I", data, 4096 + 12, 1)
    elif mutation == "outside":
        struct.pack_into("<I", data, 36, 999)
    elif mutation == "wrong_type":
        struct.pack_into("<I", data, 4096 + 8, 88)
    elif mutation == "row":
        struct.pack_into("<H", data, 8192 - 6, 65535)
    with pytest.raises(ImportFailure, match="Re-export"):
        read_pdb(bytes(data))


def test_category_search_and_empty_unknown_groups(usb, tmp_path):
    lib = import_library(usb, tmp_path / "cache")
    for category, value in [
        ("artists", "Élise"),
        ("albums", ALBUM),
        ("genres", "House"),
        ("keys", "Am"),
        ("bpm", "125–129 BPM"),
    ]:
        assert lib.browse(category).entries[0].name == value
        assert len(lib.browse(category, value).tracks) == 3
        assert len(lib.browse(category, value, "cafe").tracks) == 1
        assert lib.browse(category, query="not present").entries == ()
    assert lib.browse("playlists", "10", "empty").entries[0].id == "13"
    with pytest.raises(ValueError):
        lib.browse("unknown")
    with pytest.raises(ValueError):
        lib.browse("playlists", "removed")
    unknown = Library((Track("x", "Title", "", 1),))
    assert unknown.browse("bpm").entries[0].name == "Unknown"
    assert unknown.browse("artists").entries[0].name == "Unknown"


@pytest.mark.parametrize(
    "playlists",
    [
        (Playlist("1", "X"), Playlist("1", "X")),
        (Playlist("1", "X", "gone"),),
        (Playlist("1", "X", "1", True),),
        (Playlist("1", "X"), Playlist("2", "Y", "1")),
    ],
)
def test_invalid_playlist_hierarchies_are_rejected(playlists):
    with pytest.raises(ValueError):
        Library((), playlists)


def test_source_revision_changes_identity(usb, tmp_path):
    old = import_library(usb, tmp_path / "cache")
    (usb / "PIONEER/rekordbox/export.pdb").write_bytes(pdb_bytes(deleted=True))
    new = import_library(usb, tmp_path / "cache")
    assert old.tracks[0].id != new.tracks[0].id
    assert old.tracks[0].export_id == new.tracks[0].export_id


def test_load_rechecks_path_containment_after_symlink_replacement(usb, tmp_path):
    track = import_library(usb, tmp_path / "cache").tracks[0]
    track.audio_path.unlink()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"outside")
    track.audio_path.symlink_to(outside)
    with pytest.raises(ImportFailure, match="escapes"):
        prepare_audio(track)


def test_database_size_limit_is_actionable(usb, tmp_path, monkeypatch):
    monkeypatch.setattr("pi_dvs.rekordbox.MAX_DATABASE_BYTES", 16)
    with pytest.raises(ImportFailure, match="size limit"):
        import_library(usb, tmp_path / "cache")


@pytest.mark.parametrize("slots", [512, 513, 1024])
def test_pdb_reads_live_tracks_across_thirteen_bit_slot_directory(slots):
    data = bytearray(pdb_bytes())
    start, size = 4096, 4096
    heap_end = size - ((slots + 15) // 16) * 36
    offsets = [struct.unpack_from("<H", data, start + size - 6 - i * 2)[0] for i in range(3)]
    data[start + heap_end : start + size] = bytes(size - heap_end)
    # Allocated slots and live rows are packed as 13 + 11 bits. Deleted slots
    # still consume directory space; keep live tracks on both sides of bit 9.
    data[start + 24 : start + 27] = (slots | (3 << 13)).to_bytes(3, "little")
    data[start + 27] = 0x34
    for slot, offset in zip((0, slots // 2, slots - 1), offsets, strict=True):
        base = start + size - (slot // 16) * 36
        struct.pack_into("<H", data, base - 6 - (slot % 16) * 2, offset)
        flags = struct.unpack_from("<H", data, base - 4)[0]
        struct.pack_into("<H", data, base - 4, flags | (1 << (slot % 16)))
    assert [track.id for track in read_pdb(bytes(data)).tracks] == ["1", "2", "3"]
    # Preflight must validate the high slots too, before calling the parser.
    last_base = start + size - ((slots - 1) // 16) * 36
    struct.pack_into("<H", data, last_base - 6 - ((slots - 1) % 16) * 2, heap_end)
    with pytest.raises(ImportFailure, match="outside its data heap"):
        read_pdb(bytes(data))


@pytest.mark.parametrize("kind", ["pdb", "onelibrary"])
@pytest.mark.parametrize("failure", ["truncated", "oversized", "unreadable", "pixel_limit"])
def test_unusable_high_resolution_artwork_falls_back_to_base(
    usb, tmp_path, monkeypatch, kind, failure
):
    original = usb / ART.lstrip("/")
    high = original.with_stem("cover_m")
    high.write_bytes(b"\x89PNG\r\n\x1a\ntruncated")
    if failure == "oversized":
        high.write_bytes(bytes(128))
        monkeypatch.setattr("pi_dvs.rekordbox.MAX_ARTWORK_BYTES", 100)
    elif failure == "pixel_limit":
        Image.new("RGB", (2, 3)).save(high)
        monkeypatch.setattr("pi_dvs.rekordbox.MAX_ARTWORK_PIXELS", 4)
    elif failure == "unreadable":
        original_open = Path.open

        def open_file(path, *args, **kwargs):
            if path == high:
                raise PermissionError("unreadable preferred cover")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", open_file)
    library = import_library(usb, tmp_path / "cache", format_choice=kind)
    assert library.tracks[0].artwork is not None
    assert library.tracks[0].artwork.read_bytes() == original.read_bytes()
