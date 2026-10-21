"""Check progressive imports against the actual native dummy engine on Linux."""

import argparse
import json
import socket
import struct
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from uuid import uuid4

from pi_dvs.stream_audio import inspect_aiff, write_state
from pi_dvs.xwax.protocol import Connection, Snapshot, command_line


def status(connection: Connection, expected: str) -> Snapshot:
    deadline = monotonic() + 5
    latest = connection.status()
    while latest.state != expected and monotonic() < deadline:
        sleep(0.02)
        latest = connection.status()
    assert latest.state == expected, latest
    return latest


def fixture(directory: Path, seconds: float) -> tuple[Path, bytes, int]:
    directory.mkdir()
    frames = int(44100 * seconds)
    common = struct.pack(">hIh", 2, frames, 16) + bytes.fromhex("400eac44000000000000")
    pcm = b"\x12\x34\xfe\xdc" * frames
    body = b"AIFFCOMM" + struct.pack(">I", 18) + common
    body += b"SSND" + struct.pack(">I", len(pcm) + 8) + bytes(8) + pcm
    data = b"FORM" + struct.pack(">I", len(body)) + body
    layout = inspect_aiff(data, len(data))
    assert layout is not None
    descriptor = directory / "track.pidvs-stream"
    descriptor.write_text(json.dumps(layout.to_json()))
    return descriptor, data, layout.offset


def check(binary: Path, importer: Path) -> None:
    with TemporaryDirectory(prefix="dvs-stream-", dir="/tmp") as temporary:
        root = Path(temporary)
        endpoint = root / "a.sock"
        args = [
            str(binary),
            "--no-interface",
            "--rtprio",
            "0",
            "--protect",
            "--import",
            str(importer),
            "--socket",
            str(endpoint),
            "--dummy",
        ]
        with (root / "native.log").open("wb") as log:
            process = subprocess.Popen(args, stdout=log, stderr=log)
            try:
                deadline = monotonic() + 5
                while not endpoint.exists() and monotonic() < deadline:
                    sleep(0.02)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    sock.connect(str(endpoint))
                    connection = Connection(sock, 1)
                    status(connection, "EMPTY")
                    descriptor, data, offset = fixture(root / "long", 12)
                    prefix = offset + 44100 * 10 * 4
                    audio = descriptor.parent / "audio.aiff"
                    audio.write_bytes(data[:prefix])
                    write_state(descriptor.parent, prefix, "loading")
                    request = uuid4().hex
                    connection.command(
                        request, command_line(request, descriptor, stream_duration=12)
                    )
                    first = status(connection, "STREAMING")
                    assert first.result == "OK" and first.can_change
                    assert first.duration == 12 and first.buffered_duration == 10
                    sleep(0.15)
                    assert connection.status().state == "STREAMING"
                    with audio.open("ab") as output:
                        output.write(data[prefix:])
                    write_state(descriptor.parent, len(data), "loading")
                    until = monotonic() + 3
                    while connection.status().buffered_duration != 12 and monotonic() < until:
                        sleep(0.02)
                    assert connection.status().state == "STREAMING"
                    write_state(descriptor.parent, len(data), "complete")
                    complete = status(connection, "READY")
                    assert complete.buffered_duration == complete.duration == 12
                    # A stopped unfinished import can be unloaded immediately.
                    descriptor, data, _ = fixture(root / "cancel", 0.25)
                    (descriptor.parent / "audio.aiff").write_bytes(data)
                    write_state(descriptor.parent, len(data), "loading")
                    request = uuid4().hex
                    connection.command(
                        request, command_line(request, descriptor, stream_duration=0.25)
                    )
                    short = status(connection, "STREAMING")
                    assert short.buffered_duration == short.duration == 0.25
                    request = uuid4().hex
                    connection.command(request, command_line(request, None))
                    status(connection, "EMPTY")
                    # Terminal source loss remains an error despite emitted PCM.
                    descriptor, data, _ = fixture(root / "failure", 0.25)
                    (descriptor.parent / "audio.aiff").write_bytes(data)
                    write_state(descriptor.parent, len(data), "loading")
                    request = uuid4().hex
                    connection.command(
                        request, command_line(request, descriptor, stream_duration=0.25)
                    )
                    status(connection, "STREAMING")
                    write_state(descriptor.parent, len(data), "failed", "USB disconnected")
                    failed = status(connection, "ERROR")
                    assert failed.result == "ERROR" and failed.buffered_duration == 0.25, failed
                    request = uuid4().hex
                    connection.command(request, command_line(request, None))
                    status(connection, "EMPTY")
                    # Exit with a live producer/importer; Darwin must release
                    # the sockets and audio resources without a forced kill.
                    if sys.platform == "darwin":
                        descriptor, data, offset = fixture(root / "shutdown", 12)
                        prefix = offset + 44100 * 10 * 4
                        (descriptor.parent / "audio.aiff").write_bytes(data[:prefix])
                        write_state(descriptor.parent, prefix, "loading")
                        request = uuid4().hex
                        connection.command(
                            request, command_line(request, descriptor, stream_duration=12)
                        )
                        status(connection, "STREAMING")
                print(
                    "Native progressive import: early readiness, buffer growth, "
                    "final verification, "
                    "short track, stopped unload and source failure passed"
                )
            except BaseException:
                print((root / "native.log").read_text(errors="replace"))
                raise
            finally:
                process.terminate()
                process.wait(timeout=5)
                if sys.platform == "darwin":
                    assert process.returncode == 0, "Engine did not exit cleanly"
                    assert not endpoint.exists(), "Engine left its socket behind"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--importer", required=True, type=Path)
    options = parser.parse_args()
    check(options.engine.resolve(), options.importer.resolve())
