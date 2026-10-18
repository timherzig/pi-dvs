"""Import an already-mounted export. Discovery, hotplug and playback are separate."""

import hashlib
import math
import os
from dataclasses import replace
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Event

from PIL import Image

from pi_dvs.library import Library
from pi_dvs.model import Track
from pi_dvs.rekordbox.onelibrary import read_onelibrary
from pi_dvs.rekordbox.pdb import read_pdb
from pi_dvs.rekordbox.records import Export, ImportCancelled, ImportFailure

MAX_DATABASE_BYTES = 256 * 1024 * 1024
MAX_ARTWORK_BYTES = 8 * 1024 * 1024
MAX_ARTWORK_PIXELS = 16 * 1024 * 1024
AUDIO_EXTENSIONS = frozenset({".aiff", ".aif", ".wav", ".mp3", ".m4a", ".aac", ".flac"})


def media_path(root: Path, exported: str) -> Path:
    """A leading slash in an export means media root, not the host filesystem."""
    parts = PurePosixPath(exported.replace("\\", "/").lstrip("/")).parts
    if not parts or ".." in parts or any(":" in part or "\0" in part for part in parts):
        raise ImportFailure("Invalid path in export")
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root):
        raise ImportFailure("Export path escapes the selected media")
    return path


def _check_cancelled(event: Event) -> None:
    if event.is_set():
        raise ImportCancelled()


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ImportFailure(
            f"{path.name} exceeds the supported size limit ({limit // 1024**2} MiB)"
        )
    return data


def _artwork(root: Path, exported: str, cache: Path) -> Path | None:
    if not exported:
        return None
    try:
        original = media_path(root, exported)
    except (OSError, ImportFailure):
        return None
    for candidate in (original.with_stem(original.stem + "_m"), original):
        try:
            if not candidate.is_file():
                continue
            # Recheck after changing the filename: high-res artwork can be a symlink too.
            candidate = media_path(root, str(candidate.relative_to(root)))
            data = _read_bounded(candidate, MAX_ARTWORK_BYTES)
            # A valid signature alone does not establish that the pixels decode.
            # This runs on the import worker and does not depend on Qt.
            with Image.open(BytesIO(data), formats=["JPEG", "PNG"]) as cover:
                if cover.width * cover.height > MAX_ARTWORK_PIXELS:
                    continue
                cover.load()
            destination = cache / (hashlib.sha256(data).hexdigest() + candidate.suffix.lower())
            if not destination.exists():
                with NamedTemporaryFile(dir=cache, prefix=".cover-", delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                    try:
                        temporary.write(data)
                        temporary.close()
                        temporary_path.replace(destination)
                    finally:
                        temporary_path.unlink(missing_ok=True)
            return destination
        except (OSError, ValueError, Image.DecompressionBombError):
            continue  # Try the base cover after a broken or unreadable preferred image.
    return None


def prepare_audio(track: Track) -> Path:
    """Resolve an imported selection for an engine; does not claim decoder readiness."""
    if not track.available or track.audio_path is None:
        raise ImportFailure(track.unavailable_reason or "No audio file is available for this track")
    # This is called on a worker: it may touch removable or remote-mounted storage.
    path = (
        media_path(track.media_root, track.relative_path) if track.media_root else track.audio_path
    )
    with path.open("rb") as audio:
        if not audio.read(1):
            raise ImportFailure("The audio file is empty")
    return path


def _catalog(
    export: Export,
    root: Path,
    cache: Path,
    source: str,
    format_name: str,
    warnings: tuple[str, ...],
    cancelled: Event,
) -> Library:
    tracks = []
    for record in export.tracks:
        _check_cancelled(cancelled)
        if (
            not math.isfinite(record.duration)
            or record.duration < 0
            or not math.isfinite(record.bpm)
            or record.bpm < 0
        ):
            raise ImportFailure("Invalid duration or BPM in export")
        audio: Path | None = None
        reason = ""
        try:
            audio = media_path(root, record.path)
            if audio.suffix.lower() not in AUDIO_EXTENSIONS:
                reason = f"Unsupported audio format: {audio.suffix or 'no extension'}"
            elif not audio.is_file() or not os.access(audio, os.R_OK):
                reason = "Audio file is missing or unreadable"
            elif audio.stat().st_size == 0:
                reason = "Audio file is empty"
        except (OSError, ImportFailure):
            reason = "Audio path is invalid or outside the selected USB"
        tracks.append(
            Track(
                id=f"{source}:{record.id}",
                title=record.title or "Untitled",
                artist=record.artist or "Unknown",
                duration=record.duration,
                artwork=_artwork(root, record.artwork, cache),
                available=not reason,
                audio_path=audio,
                source_id=source,
                export_id=record.id,
                media_root=root,
                relative_path=record.path.replace("\\", "/").lstrip("/"),
                album=record.album,
                genre=record.genre,
                key=record.key,
                bpm=record.bpm,
                unavailable_reason=reason,
            )
        )
    known = {t.export_id for t in tracks}
    missing_entries = sum(t not in known for p in export.playlists for t in p.track_ids)
    if missing_entries:
        warnings += (
            f"{missing_entries} playlist entries reference tracks absent from the export.",
        )
    playlists = tuple(
        replace(p, track_ids=tuple(f"{source}:{i}" for i in p.track_ids if i in known))
        for p in export.playlists
    )
    return Library(
        tuple(tracks),
        playlists,
        name=root.name,
        source_id=source,
        format_name=format_name,
        warnings=warnings,
    )


def import_library(
    root: Path, cache: Path, *, format_choice: str = "auto", cancelled: Event | None = None
) -> Library:
    """Auto prefers traditional PDB; explicit format selection permits both views.

    Failed PDB reads can fall back to OneLibrary with a visible warning. We never
    union their IDs: the formats can contain different IDs, playlists or revisions.
    """
    event = cancelled or Event()
    _check_cancelled(event)
    root = root.expanduser().resolve()
    cache = cache.expanduser().resolve()
    if cache.is_relative_to(root):
        raise ImportFailure("Choose an artwork cache outside the source USB")
    if format_choice not in ("auto", "pdb", "onelibrary"):
        raise ImportFailure("Choose Auto, Device Library, or OneLibrary")
    candidates = [
        ("pdb", "export.pdb", "Device Library"),
        ("onelibrary", "exportLibrary.db", "OneLibrary"),
    ]
    failures: list[str] = []
    for kind, filename, label in candidates:
        if format_choice not in ("auto", kind):
            continue
        path = root / "PIONEER" / "rekordbox" / filename
        if not path.is_file():
            continue
        try:
            path = media_path(root, str(path.relative_to(root)))
            data = _read_bounded(path, MAX_DATABASE_BYTES)
            # Identity includes media location AND database revision: replacement USBs
            # cannot collide merely because they reuse a track ID or volume name.
            source = hashlib.sha256(os.fsencode(root) + b"\0" + data).hexdigest()
            cache.mkdir(parents=True, exist_ok=True)
            if kind == "pdb":
                export = read_pdb(data)
            else:
                # A private snapshot keeps hashing and SQL queries on exactly the same
                # bytes, and even a database recovery attempt cannot affect the USB.
                with TemporaryDirectory(prefix="pi-dvs-import-") as temporary:
                    snapshot = Path(temporary) / filename
                    snapshot.write_bytes(data)
                    export = read_onelibrary(snapshot, event)
            warnings = tuple(failures)
            if kind == "pdb" and (path.parent / "exportLibrary.db").is_file():
                warnings += (
                    "Both libraries found; using Device Library. "
                    "Select OneLibrary to browse its view.",
                )
            library = _catalog(export, root, cache, source, label, warnings, event)
            _check_cancelled(event)
            return library
        except (OSError, ValueError) as error:
            failures.append(f"{label}: {error}")
    if failures:
        raise ImportFailure("Import failed. " + " ".join(failures))
    raise ImportFailure(
        "No supported export found. Select the USB root containing PIONEER/rekordbox, "
        "or export Device Library/OneLibrary from rekordbox first."
    )
