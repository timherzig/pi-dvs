"""The pinned engine's DVS2 extension. No Qt, filesystem I/O or audio processing."""

import math
import socket
from dataclasses import dataclass
from pathlib import Path
from time import monotonic


class ProtocolError(ValueError):
    """The peer is not the supported patched engine, or sent malformed state."""


@dataclass(frozen=True)
class Snapshot:
    request_id: str
    result: str
    state: str
    active: bool
    protected: bool
    timecode_control: bool
    position_known: bool
    elapsed: float
    duration: float
    pitch: float
    path: str

    @property
    def can_change(self) -> bool:
        return (
            self.protected
            and not self.active
            and self.state != "IMPORTING"
            and self.result != "PENDING"
        )


def parse_status(line: str) -> Snapshot:
    if line == "DVS2 STALE":
        raise ProtocolError("xwax audio callbacks stopped; check the audio device and engine log")
    fields = line.split(" ", 12)
    if len(fields) != 13 or fields[:2] != ["DVS2", "STATE"]:
        raise ProtocolError("Expected the pinned pi-dvs DVS2 engine; rebuild it with our patch")
    (
        _,
        _,
        request_id,
        result,
        state,
        active,
        protected,
        timecode_control,
        known,
        elapsed,
        duration,
        pitch,
        path,
    ) = fields
    if request_id != "-" and (
        len(request_id) != 32 or any(c not in "0123456789abcdef" for c in request_id)
    ):
        raise ProtocolError("Invalid engine request identifier")
    if result not in {"NONE", "PENDING", "OK", "LOCKED", "ERROR"} or state not in {
        "EMPTY",
        "IMPORTING",
        "READY",
        "ERROR",
    }:
        raise ProtocolError("Unknown engine result or state")
    if any(v not in {"0", "1"} for v in (active, protected, timecode_control, known)):
        raise ProtocolError("Invalid engine flags")
    try:
        numbers = tuple(float(v) for v in (elapsed, duration, pitch))
    except ValueError as error:
        raise ProtocolError("Invalid engine position") from error
    if not all(math.isfinite(v) for v in numbers) or numbers[1] < 0:
        raise ProtocolError("Invalid engine position or duration")
    if (state == "EMPTY" and path) or (state != "EMPTY" and not path.startswith("/")):
        raise ProtocolError("Invalid engine track path")
    if any(c in path for c in "\r\n\0"):
        raise ProtocolError("Invalid engine track path")
    return Snapshot(
        request_id,
        result,
        state,
        active == "1",
        protected == "1",
        timecode_control == "1",
        known == "1",
        numbers[0],
        numbers[1],
        numbers[2],
        path,
    )


def command_line(request_id: str, path: Path | None) -> bytes:
    command = f"DVS2 UNLOAD {request_id}" if path is None else f"DVS2 LOAD {request_id} {path}"
    if path is not None and not path.is_absolute():
        raise ValueError("xwax requires an absolute audio path")
    if any(c in command for c in "\n\r\0"):
        raise ValueError("xwax paths cannot contain newline, carriage return or NUL")
    try:
        encoded = (command + "\n").encode("utf-8")
    except UnicodeError as error:
        raise ValueError("xwax requires UTF-8 audio paths") from error
    if len(encoded) > 1023:
        raise ValueError("Audio path exceeds the pinned engine's command limit")
    return encoded


class Connection:
    """One owner serializes commands and status queries on a persistent socket."""

    def __init__(self, sock: socket.socket, timeout: float) -> None:
        self.sock = sock
        self.timeout = timeout
        self.buffer = bytearray()

    def exchange(self, command: bytes) -> str:
        deadline = monotonic() + self.timeout
        self.sock.settimeout(self.timeout)
        self.sock.sendall(command)
        while b"\n" not in self.buffer:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Engine response timed out")
            self.sock.settimeout(remaining)
            data = self.sock.recv(4096)
            if not data:
                raise ConnectionError("Engine disconnected")
            self.buffer.extend(data)
            if len(self.buffer) > 8192:
                raise ProtocolError("Engine response exceeds the protocol limit")
        line, _, tail = self.buffer.partition(b"\n")
        self.buffer = bytearray(tail)
        try:
            return line.decode("utf-8")
        except UnicodeError as error:
            raise ProtocolError("Engine response is not UTF-8") from error

    def status(self) -> Snapshot:
        return parse_status(self.exchange(b"DVS2 STATUS\n"))

    def command(self, request_id: str, line: bytes) -> None:
        response = self.exchange(line).split(" ")
        if len(response) != 4 or response[:3] != ["DVS2", "ACK", request_id]:
            raise ProtocolError("Engine did not acknowledge this request")
        result = response[3]
        if result != "ACCEPTED":
            messages = {
                "BUSY": "Engine is busy; retry when it is ready",
                "LOCKED": "Stop the record before changing tracks",
                "UNPROTECTED": "Start xwax with --protect before loading tracks",
                "INVALID": "Engine rejected the audio path or command",
                "ERROR": "Engine could not accept the command",
            }
            if result not in messages:
                raise ProtocolError("Unknown engine acknowledgement")
            raise CommandRejected(messages[result])


class CommandRejected(ValueError):
    """A confirmed rejection; the current track remains authoritative."""
