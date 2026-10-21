"""Small, validated remote-cover cache, independent of Qt and audio state."""

import hashlib
import time
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, RLock

from PIL import Image

from pi_dvs.link.media import Cancel
from pi_dvs.rekordbox import MAX_ARTWORK_PIXELS

MAX_COVER_BYTES = 512 * 1024


class Covers:
    def __init__(self, root: Path, limit: int = 64 * 1024 * 1024) -> None:
        self.root, self.limit = root, limit
        self._lock = RLock()
        self._io = Lock()
        self._resident: set[Path] = set()
        self._pinned: set[Path] = set()
        self._known: dict[tuple[str, str], Path] = {}

    def protect(self, paths: tuple[Path, ...]) -> None:
        with self._lock:
            self._pinned = set(paths)

    def paths(self) -> frozenset[Path]:
        with self._lock:
            return frozenset(self._resident)

    def find(self, key: tuple[str, str]) -> Path | None:
        with self._io:
            path = self._known.get(key)
            return path if path is not None and path.is_file() else None

    def store(self, key: tuple[str, str], data: bytes, cancelled: Cancel) -> Path | None:
        if len(data) > MAX_COVER_BYTES:
            return None
        try:
            with Image.open(BytesIO(data), formats=["JPEG", "PNG"]) as cover:
                if cover.width * cover.height > MAX_ARTWORK_PIXELS:
                    return None
                cover.load()
                suffix = ".jpg" if cover.format == "JPEG" else ".png"
        except (OSError, ValueError, Image.DecompressionBombError):
            return None
        cancelled.check()
        # Filesystem operations use a worker-only lock. GUI pin/validity snapshots
        # never wait for disk I/O, including blocked temporary writes.
        with self._io:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / ("cover-" + hashlib.sha256(data).hexdigest() + suffix)
            entries = sorted(self.root.glob("cover-*"), key=lambda p: p.stat().st_mtime_ns)
            used = sum(p.stat().st_size for p in entries)
            count = len(entries)
            extra = 0 if target.exists() else len(data)
            for path in entries:
                if used + extra <= self.limit and count < 512:
                    break
                size = path.stat().st_size
                with self._lock:
                    evict = path not in self._pinned and path != target
                    if evict:
                        self._resident.discard(path)
                if evict:
                    path.unlink()
                    used -= size
                    count -= 1
            if used + extra > self.limit or count >= 512:
                return None
            cancelled.check()
            with NamedTemporaryFile(dir=self.root, prefix=".cover-", delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(data)
                    stream.close()
                    cancelled.check()
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            with self._lock:
                self._resident.add(target)
                resident = frozenset(self._resident)
            self._known = {k: v for k, v in self._known.items() if v in resident}
            # Bound aliases too: many tracks/generations can refer to the same cover.
            if len(self._known) >= 1024:
                self._known.pop(next(iter(self._known)))
            self._known[key] = target
            return target


class CoverCancel(Cancel):
    """Bound cover I/O after it acquires the shared transfer queue."""

    def __init__(self, parent: Cancel, seconds: float = 8) -> None:
        super().__init__(parent)
        self.until = time.monotonic() + seconds

    def is_set(self) -> bool:
        return super().is_set() or time.monotonic() >= self.until
