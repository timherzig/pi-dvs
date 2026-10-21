"""Private progressive AIFF format and xwax importer; standard library only.

The same module is copied beside the separately built native engine. All waiting
and file I/O happens in its importer process, never in the audio callback.
"""

import json
import math
import struct
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

VERSION = 1
MAX_HEADER = 1024 * 1024
STALE_SECONDS = 15.0
SUFFIX = ".pidvs-stream"


class UnsupportedAudio(ValueError):
    """The ordinary complete-file decoder must handle this layout."""


@dataclass(frozen=True)
class Layout:
    file_size: int
    offset: int
    frames: int
    rate: int = 44100

    @property
    def duration(self) -> float:
        return self.frames / self.rate

    @property
    def end(self) -> int:
        return self.offset + self.frames * 4

    def to_json(self) -> dict[str, int]:
        return {"version": VERSION, **asdict(self)}


def inspect_aiff(data: bytes, file_size: int) -> Layout | None:
    """None means more header bytes are needed; unsupported layouts fall back."""
    if len(data) < 12:
        return None
    if data[:4] != b"FORM" or data[8:12] != b"AIFF":
        raise UnsupportedAudio("Progressive playback requires uncompressed AIFF")
    form_end = struct.unpack_from(">I", data, 4)[0] + 8
    if form_end != file_size:
        raise UnsupportedAudio("AIFF FORM size does not match the source")
    offset, frames = 12, None
    while offset + 8 <= min(len(data), MAX_HEADER):
        kind, size = struct.unpack_from(">4sI", data, offset)
        start, end = offset + 8, offset + 8 + size
        if end > form_end or end + size % 2 > form_end:
            raise UnsupportedAudio("AIFF chunk exceeds the source")
        if kind == b"COMM":
            if frames is not None or size != 18:
                raise UnsupportedAudio("Unsupported AIFF common chunk")
            if end > len(data):
                return None
            channels, frames, bits = struct.unpack_from(">hIh", data, start)
            # Exact 80-bit extended representation of 44100. No float ambiguity.
            if (
                channels != 2
                or bits != 16
                or not frames
                or data[start + 8 : end] != bytes.fromhex("400eac44000000000000")
            ):
                raise UnsupportedAudio("Progressive AIFF requires stereo PCM16 at 44100 Hz")
        elif kind == b"SSND":
            if frames is None or size < 8:
                raise UnsupportedAudio("AIFF sound precedes its format or is truncated")
            if start + 8 > len(data):
                return None
            skip, block_size = struct.unpack_from(">II", data, start)
            pcm = start + 8 + skip
            if block_size or pcm + frames * 4 != end:
                raise UnsupportedAudio("Unsupported AIFF sound layout")
            return Layout(file_size, pcm, frames)
        offset = end + size % 2
        if offset > MAX_HEADER:
            raise UnsupportedAudio("AIFF header is too large for progressive playback")
    if len(data) >= MAX_HEADER or len(data) >= file_size:
        raise UnsupportedAudio("AIFF sound chunk was not found")
    return None


def write_state(directory: Path, available: int, status: str, error: str = "") -> None:
    """One producer publishes a committed prefix only after flushing its file."""
    value = {
        "available": available,
        "status": status,
        "error": error,
        "updated": time.monotonic(),
    }
    temporary = directory / "state.next"
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(directory / "state.json")


def read_object(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        data = stream.read(4097)
    if len(data) > 4096:
        raise ValueError("Stream metadata is too large")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Invalid stream metadata")
    return value


def layout_from_descriptor(path: Path) -> Layout:
    value = read_object(path)
    if value.get("version") != VERSION:
        raise ValueError("Unsupported stream descriptor")
    fields = [value.get(name) for name in ("file_size", "offset", "frames", "rate")]
    if any(type(v) is not int for v in fields):
        raise ValueError("Invalid stream layout")
    size, offset, frames, rate = (int(str(v)) for v in fields)
    layout = Layout(size, offset, frames, rate)
    if not (12 <= offset < size <= 512 * 1024**2 and frames > 0 and rate == 44100):
        raise ValueError("Invalid stream limits")
    if layout.end > size:
        raise ValueError("Stream audio exceeds the source")
    return layout


def import_stream(descriptor: Path, output: BinaryIO, *, stale: float = STALE_SECONDS) -> None:
    """Output PCM16LE, waiting at temporary EOF and failing on terminal loss."""
    layout = layout_from_descriptor(descriptor)
    position, previous = layout.offset, 0
    with (descriptor.parent / "audio.aiff").open("rb") as source:
        # Verify descriptor against actual source bytes, independent of the GUI.
        header = source.read(min(layout.offset, MAX_HEADER))
        if inspect_aiff(header, layout.file_size) != layout:
            raise ValueError("Stream header differs from its descriptor")
        source.seek(position)
        while True:
            state = read_object(descriptor.parent / "state.json")
            available, status, updated = (
                state.get("available"),
                state.get("status"),
                state.get("updated"),
            )
            if (
                type(available) is not int
                or not isinstance(updated, (float, int))
                or not math.isfinite(updated)
                or status not in ("loading", "complete", "failed")
            ):
                raise ValueError("Invalid stream state")
            if not previous <= available <= layout.file_size:
                raise ValueError("Stream prefix moved backwards or exceeded the source")
            previous = available
            if status == "failed":
                raise ValueError(str(state.get("error") or "Audio download interrupted"))
            if status == "complete" and available != layout.file_size:
                raise ValueError("Stream completed before its source was verified")
            if status == "loading" and time.monotonic() - updated > stale:
                raise TimeoutError("Audio download stopped responding")
            end = min(available, layout.end)
            length = max(0, (end - position) // 4 * 4)
            if length:
                data = source.read(min(length, 65536))
                if len(data) != min(length, 65536):
                    raise ValueError("Committed audio is missing from the stream")
                # AIFF PCM16 is big endian; xwax imports signed little endian PCM.
                swapped = bytearray(len(data))
                swapped[0::2], swapped[1::2] = data[1::2], data[0::2]
                view = memoryview(swapped)
                while view:
                    written = output.write(view)
                    if written is None or written <= 0:
                        raise OSError("PCM output stopped accepting audio")
                    view = view[written:]
                output.flush()
                position += len(data)
            elif position == layout.end and status == "complete":
                return
            else:
                time.sleep(0.02)


def main() -> int:
    try:
        if len(sys.argv) != 3 or sys.argv[2] != "44100":
            raise ValueError("Usage: stream-import DESCRIPTOR 44100")
        import_stream(Path(sys.argv[1]), sys.stdout.buffer)
    except (OSError, ValueError) as error:
        print(f"pi-dvs stream: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
