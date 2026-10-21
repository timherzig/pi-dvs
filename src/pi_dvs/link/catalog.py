"""Translate exported USB metadata for browsing and the separate Link server."""

import hashlib
import math
import os
from dataclasses import replace
from pathlib import Path

from pi_dvs.library import Library
from pi_dvs.link.media import Media
from pi_dvs.model import Track
from pi_dvs.rekordbox import AUDIO_EXTENSIONS, media_path
from pi_dvs.rekordbox.pdb import read_pdb
from pi_dvs.rekordbox.records import ImportFailure


def local_token(root: Path) -> str:
    identity = root.stat()
    values = [str(identity.st_dev), str(identity.st_ino)]
    found = False
    for filename in ("export.pdb", "exportLibrary.db"):
        path = root / "PIONEER/rekordbox" / filename
        try:
            info = path.stat()
        except FileNotFoundError:
            values.append("absent")
        else:
            if not path.resolve().is_relative_to(root):
                raise ImportFailure("Export database escapes selected USB")
            found = True
            values += [
                filename,
                str(info.st_dev),
                str(info.st_ino),
                str(info.st_size),
                str(info.st_mtime_ns),
                str(info.st_ctime_ns),
            ]
    if not found:
        raise FileNotFoundError("USB export is not present")
    return hashlib.sha256("|".join(values).encode()).hexdigest()


def remote_library(data: bytes, media: Media) -> Library:
    export = read_pdb(data)
    tracks = []
    for t in export.tracks:
        if not math.isfinite(t.duration) or t.duration < 0 or not math.isfinite(t.bpm) or t.bpm < 0:
            raise ImportFailure("Invalid duration or BPM in CDJ export")
        relative = t.path.replace("\\", "/").lstrip("/")
        reason = ""
        try:
            # Validate lexical traversal without treating the remote path as local audio.
            media_path(Path("/pi-dvs-remote"), relative)
            if Path(relative).suffix.lower() not in AUDIO_EXTENSIONS:
                reason = "Unsupported audio format"
        except (OSError, ImportFailure):
            reason = "Invalid path in CDJ export"
        tracks.append(
            Track(
                id=f"{media.source_id}:{t.id}",
                title=t.title or "Untitled",
                artist=t.artist or "Unknown",
                duration=t.duration,
                source_id=media.source_id,
                export_id=t.id,
                relative_path=relative,
                album=t.album,
                genre=t.genre,
                key=t.key,
                bpm=t.bpm,
                available=not reason,
                unavailable_reason=reason,
                analysis_path=t.analysis_path,
                artwork_path=t.artwork,
                sample_rate=t.sample_rate,
                bitrate=t.bitrate,
                bit_depth=t.bit_depth,
            )
        )
    known = {t.export_id for t in tracks}
    playlists = tuple(
        replace(p, track_ids=tuple(f"{media.source_id}:{i}" for i in p.track_ids if i in known))
        for p in export.playlists
    )
    return Library(
        tuple(tracks), playlists, name=media.name, source_id=media.source_id, format_name="CDJ USB"
    )


def serving_catalog(library: Library, root: Path) -> dict[str, object]:
    database = (
        root
        / "PIONEER/rekordbox"
        / ("export.pdb" if library.format_name == "Device Library" else "exportLibrary.db")
    )
    tracks: list[dict[str, object]] = []
    types = {".mp3": 1, ".m4a": 4, ".aac": 4, ".wav": 11, ".aif": 12, ".aiff": 12}
    for track in library.tracks:
        if not track.available:
            continue
        path = media_path(root, track.relative_path)
        if path.suffix.lower() not in types:
            continue  # Original CDJ-900 does not support FLAC.
        try:
            numeric_id = int(track.export_id)
        except ValueError as error:
            raise ImportFailure("CDJ serving requires numeric export track IDs") from error
        if not 0 < numeric_id < 2**32:
            raise ImportFailure("Export track ID exceeds the CDJ protocol range")

        def asset(value: str) -> str:
            if not value:
                return ""
            try:
                candidate = media_path(root, value)
                return candidate.relative_to(root).as_posix() if candidate.is_file() else ""
            except (OSError, ImportFailure):
                return ""

        tracks.append(
            dict(
                id=numeric_id,
                title=track.title,
                artist=track.artist,
                album=track.album,
                genre=track.genre,
                key=track.key,
                path=os.fspath(path),
                analysis=asset(track.analysis_path),
                artwork=asset(track.artwork_path),
                duration=round(track.duration),
                bpm=round(track.bpm * 100),
                sample_rate=track.sample_rate,
                bitrate=track.bitrate,
                bit_depth=track.bit_depth,
                file_type=types[path.suffix.lower()],
            )
        )
    return dict(
        root=os.fspath(root),
        database=os.fspath(database),
        tracks=tracks,
        playlists=[
            dict(
                id=int(p.id),
                name=p.name,
                parent=int(p.parent_id) if p.parent_id else None,
                folder=p.is_folder,
                order=p.order,
                tracks=[int(i.rsplit(":", 1)[1]) for i in p.track_ids],
            )
            for p in library.playlists
        ],
    )
