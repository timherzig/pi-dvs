"""Bounded, paced NFSv2 reads using the CDJ UTF-16 filename dialect.

Wire references: RFC 1094 and Deep Symmetry's DJ Link media analysis. Only
PORTMAP GETPORT, MOUNT/UMNT, LOOKUP and READ are implemented. No source writes.
"""

import hashlib
import os
import secrets
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from threading import Event
from typing import Protocol

from pi_dvs.rekordbox.records import ImportCancelled, ImportFailure

RATE = 256 * 1024
BLOCK = 1280


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


class NfsError(ImportFailure):
    def __init__(self, operation: str, status: int) -> None:
        self.status = status
        reason = {2: "file missing", 13: "media unavailable", 70: "stale media handle"}.get(
            status, f"status {status}"
        )
        super().__init__(f"CDJ {operation}: {reason}")


def words(*values: int) -> bytes:
    return struct.pack(f">{len(values)}I", *values)


def opaque(value: bytes) -> bytes:
    return words(len(value)) + value + bytes(-len(value) % 4)


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def take(self, count: int) -> bytes:
        if count < 0 or count > len(self.data) - self.offset:
            raise ImportFailure("Truncated CDJ response")
        result = self.data[self.offset : self.offset + count]
        self.offset += count
        return result

    def integer(self) -> int:
        return int(struct.unpack(">I", self.take(4))[0])

    def opaque(self, maximum: int) -> bytes:
        length = self.integer()
        if length > maximum:
            raise ImportFailure("Oversized CDJ response")
        result = self.take(length)
        self.take(-length % 4)
        return result

    def rest(self) -> bytes:
        return self.take(len(self.data) - self.offset)


@dataclass(frozen=True)
class FileInfo:
    handle: bytes
    attributes: tuple[int, ...]

    @property
    def size(self) -> int:
        return self.attributes[5]

    @property
    def identity(self) -> tuple[int, ...]:
        # fsid, fileid, size, mtime and ctime (not read-sensitive atime).
        a = self.attributes
        return a[9:11] + (a[5],) + a[13:17]

    def matches_read(self, attributes: tuple[int, ...]) -> bool:
        # Original CDJ-900 4.32 returns only fileid in READ attributes.
        if not any(attributes[i] for i in (0, 5, 9, 13, 14, 15, 16)):
            return attributes[10] == self.attributes[10]
        return FileInfo(self.handle, attributes).identity == self.identity


@dataclass(frozen=True)
class Download:
    size: int
    sha256: str
    identity: tuple[int, ...]
    retries: int


class Client:
    """One owner, one outstanding request, one mount; close after each operation."""

    def __init__(
        self,
        local_ip: str,
        *,
        cancelled: Cancellation | None = None,
        timeout: float = 1.0,
        attempts: int = 3,
        interval: float = BLOCK / RATE,
    ) -> None:
        if timeout <= 0 or attempts < 1 or interval < 0:
            raise ValueError("Invalid transfer limits")
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind((local_ip, 0))
        except OSError:
            self.socket.close()
            raise
        self.cancelled = cancelled or Event()
        self.timeout, self.attempts, self.interval = timeout, attempts, interval
        self.deadline = float("inf")
        self.next_send = 0.0
        self.xid = secrets.randbits(32)
        self.retries = 0
        self.root: bytes | None = None
        self.mount_host: tuple[str, int] | None = None
        self.nfs_host: tuple[str, int] | None = None

    def check(self) -> None:
        if self.cancelled.is_set():
            raise ImportCancelled()
        if time.monotonic() >= self.deadline:
            raise TimeoutError("CDJ transfer deadline exceeded")

    def rpc(
        self, host: tuple[str, int], program: int, version: int, procedure: int, payload: bytes
    ) -> bytes:
        self.check()
        self.xid = (self.xid + 1) & 0xFFFFFFFF
        xid = self.xid
        # AUTH_UNIX: stamp, empty hostname, uid, gid, no supplementary groups.
        credential = words(0x50494456, 0, 0, 0, 0)
        packet = words(xid, 0, 2, program, version, procedure, 1)
        packet += opaque(credential) + words(0, 0) + payload
        for attempt in range(self.attempts):
            while time.monotonic() < self.next_send:
                self.check()
                time.sleep(max(0.0, min(0.02, self.next_send - time.monotonic())))
            self.check()
            self.socket.sendto(packet, host)
            self.next_send = time.monotonic() + self.interval
            until = min(self.deadline, time.monotonic() + self.timeout)
            while time.monotonic() < until:
                self.check()
                self.socket.settimeout(max(0.0001, min(0.1, until - time.monotonic())))
                try:
                    data, peer = self.socket.recvfrom(65536)
                except TimeoutError:
                    continue
                if peer != host:
                    continue
                reader = Reader(data)
                try:
                    if reader.integer() != xid or reader.integer() != 1:
                        continue
                    accepted = reader.integer()
                    if accepted:
                        raise NfsError("RPC denied", accepted)
                    reader.integer()  # verifier flavor
                    reader.opaque(400)
                    status = reader.integer()
                except NfsError:
                    raise
                except ImportFailure:
                    continue  # malformed datagrams do not consume the attempt
                if status:
                    raise NfsError("RPC rejected", status)
                return reader.rest()
            if attempt + 1 < self.attempts:
                self.retries += 1
        raise TimeoutError(f"CDJ did not reply after {self.attempts} attempts")

    def mount(self, ip: str, portmap_port: int = 111) -> None:
        self.deadline = time.monotonic() + 12
        try:

            def port(program: int, version: int) -> int:
                response = self.rpc(
                    (ip, portmap_port), 100000, 2, 3, words(program, version, 17, 0)
                )
                value = Reader(response).integer()
                if not 0 < value <= 65535:
                    raise ImportFailure("CDJ file service is unavailable")
                return value

            self.mount_host = (ip, port(100005, 1))
            self.nfs_host = (ip, port(100003, 2))
            reader = Reader(
                self.rpc(self.mount_host, 100005, 1, 1, opaque("/C/".encode("utf-16-le")))
            )
            status = reader.integer()
            if status:
                raise NfsError("mount", status)
            self.root = reader.take(32)
        finally:
            self.deadline = float("inf")

    def nfs(self, procedure: int, payload: bytes) -> Reader:
        if self.nfs_host is None:
            raise ImportFailure("CDJ source is not mounted")
        reader = Reader(self.rpc(self.nfs_host, 100003, 2, procedure, payload))
        status = reader.integer()
        if status:
            raise NfsError({4: "lookup", 6: "read"}.get(procedure, "request"), status)
        return reader

    @staticmethod
    def attributes(reader: Reader) -> tuple[int, ...]:
        return tuple(reader.integer() for _ in range(17))

    def lookup(self, path: str) -> FileInfo:
        previous = self.deadline
        self.deadline = min(previous, time.monotonic() + 15)
        try:
            return self._lookup(path)
        finally:
            self.deadline = previous

    def _lookup(self, path: str) -> FileInfo:
        parts = PurePosixPath(path).parts
        if not parts or ".." in parts or "\\" in path or "\0" in path or len(path) > 4096:
            raise ImportFailure("Invalid CDJ file path")
        handle = self.root
        if handle is None:
            raise ImportFailure("CDJ source is not mounted")
        result = None
        for part in parts:
            if part == "/":
                continue
            reader = self.nfs(4, handle + opaque(part.encode("utf-16-le")))
            handle = reader.take(32)
            result = FileInfo(handle, self.attributes(reader))
        if result is None or result.attributes[0] != 1:
            raise ImportFailure("CDJ path is not a regular file")
        return result

    def download(
        self,
        path: str,
        destination: Path,
        *,
        max_bytes: int = 512 * 1024 * 1024,
        expected_sha256: str | None = None,
        expected_identity: tuple[int, ...] | None = None,
    ) -> Download:
        self.deadline = time.monotonic() + 15
        temporary: Path | None = None
        before = self.retries
        try:
            if destination.exists():
                raise FileExistsError(destination)
            info = self.lookup(path)
            if not 0 < info.size <= max_bytes:
                raise ImportFailure(f"Invalid or excessive CDJ file size: {info.size}")
            if expected_identity is not None and info.identity != expected_identity:
                raise ImportFailure("CDJ media changed before download")
            self.deadline = time.monotonic() + 15 + info.size / RATE * 2
            digest = hashlib.sha256()
            offset = 0
            with NamedTemporaryFile(
                dir=destination.parent, prefix=".partial-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                while offset < info.size:
                    wanted = min(BLOCK, info.size - offset)
                    reader = self.nfs(6, info.handle + words(offset, wanted, 0))
                    if not info.matches_read(self.attributes(reader)):
                        raise ImportFailure("CDJ file changed during download")
                    data = reader.opaque(wanted)
                    if not data:
                        raise ImportFailure("CDJ returned an empty read")
                    stream.write(data)
                    digest.update(data)
                    offset += len(data)
                stream.flush()
                os.fsync(stream.fileno())
            if self.lookup(path).identity != info.identity:
                raise ImportFailure("CDJ file changed before publication")
            checksum = digest.hexdigest()
            if expected_sha256 is not None and checksum != expected_sha256:
                raise ImportFailure("CDJ file checksum differs")
            self.check()
            os.link(temporary, destination)
            return Download(offset, checksum, info.identity, self.retries - before)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            self.deadline = float("inf")

    def close(self) -> None:
        try:
            if (
                self.root is not None
                and self.mount_host is not None
                and not self.cancelled.is_set()
            ):
                self.deadline = time.monotonic() + 1
                try:
                    self.rpc(self.mount_host, 100005, 1, 3, opaque("/C/".encode("utf-16-le")))
                except (OSError, ImportFailure, ImportCancelled):
                    pass
        finally:
            self.socket.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
