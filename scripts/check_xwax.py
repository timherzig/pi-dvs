"""Exercise the real pinned binary on Linux, without an audio device or Qt."""

import argparse
import shlex
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from pi_dvs.model import Status, Track
from pi_dvs.xwax import XwaxEngine
from pi_dvs.xwax.protocol import Connection


def until(condition: Callable[[], bool], label: str, timeout: float = 10) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if condition():
            return
        sleep(0.02)
    raise AssertionError(f"Timed out: {label}")


def smoke(binary: Path, importer: Path) -> None:
    fixture = Path("tests/fixtures/usb/Contents/Élise/Café 東京.wav").resolve()
    assert fixture.is_file(), fixture
    with TemporaryDirectory(prefix="dvs-smoke-", dir="/tmp") as directory:
        root = Path(directory)
        endpoints = (root / "a.sock", root / "b.sock")
        # Simulate an importer failing after it has emitted PCM. The audio path
        # stays entirely in the engine and its importer, never in Python.
        partial = root / "partial failure.wav"
        shutil.copyfile(fixture, partial)
        wrapper = root / "import-with-failure"
        wrapper.write_text(
            "#!/bin/sh\n"
            + shlex.quote(str(importer))
            + ' "$@"\n'
            + 'status=$?\ncase "$1" in *"partial failure.wav") exit 1;; esac\nexit "$status"\n'
        )
        wrapper.chmod(0o755)
        args = [
            str(binary),
            "--no-interface",
            "--rtprio",
            "0",
            "--protect",
            "--import",
            str(wrapper),
        ]
        for endpoint in endpoints:
            args += ["--socket", str(endpoint), "--dummy"]
        log = root / "engine.log"
        client: XwaxEngine | None = None
        with log.open("wb") as output:
            process = subprocess.Popen(args, stdout=output, stderr=output)
            try:
                client = XwaxEngine(endpoints, poll=0.02)
                engine = client
                until(
                    lambda: all(
                        d.status == Status.EMPTY and d.can_change_track for d in engine.decks
                    ),
                    "two protected decks",
                )
                track = Track("fixture", "Synthetic PCM", "pi-dvs", 1, audio_path=fixture)
                engine.load(0, track)
                engine.load(1, track)
                until(
                    lambda: all(d.status == Status.READY for d in engine.decks),
                    "both actual imports",
                )
                assert all(d.track and abs(d.track.duration - 1) < 0.02 for d in engine.decks)
                engine.unload(0)
                until(lambda: engine.decks[0].status == Status.EMPTY, "unload A")
                assert engine.decks[1].status == Status.READY
                # File existence/preflight alone must not imply decoder success.
                bad = root / "corrupt audio.wav"
                bad.write_bytes(b"not a wave file")
                for audio in (bad, root / "missing file.wav", partial):
                    engine.load(0, Track("bad", "Bad", "", 1, audio_path=audio))
                    until(lambda: engine.decks[0].status == Status.ERROR, "confirmed failed import")
                    assert engine.decks[0].error
                shutil.copyfile(fixture, bad)
                engine.load(0, Track("repaired", "Repaired", "", 1, audio_path=bad))
                until(lambda: engine.decks[0].status == Status.READY, "retry repaired failed path")
                engine.load(0, track)
                until(lambda: engine.decks[0].status == Status.READY, "recovery")
                # Same-path loads must be confirmed even when xwax reuses decoded PCM.
                engine.load(0, track)
                until(lambda: engine.decks[0].status == Status.READY, "same-path reload")
                engine.close()
                for worker in engine._connections:
                    worker.thread.join(2)
                client = XwaxEngine(endpoints, poll=0.02)
                engine = client
                until(
                    lambda: all(d.status == Status.READY for d in engine.decks),
                    "reconnect adopts tracks",
                )
                assert all(d.track and d.track.audio_path == fixture for d in engine.decks)
                engine.close()
                for worker in engine._connections:
                    worker.thread.join(2)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.connect(str(endpoints[0]))
                    connection = Connection(sock, 1)
                    assert connection.exchange(b"DVS2 METRICS\n") == "DVS2 METRICS 0 0 0"
                    assert connection.exchange(b"PLAY\n") == "DVS2 UNSUPPORTED"
                    assert connection.status().timecode_control
                client = XwaxEngine(endpoints, poll=0.02)
                engine = client
                until(lambda: engine.decks[0].status == Status.READY, "adopt ready deck")
                process.terminate()
                process.wait(timeout=5)
                if sys.platform == "darwin":
                    assert process.returncode == 0, "Engine did not exit cleanly"
                    assert not any(endpoint.exists() for endpoint in endpoints)
                until(
                    lambda: all(d.status == Status.DISCONNECTED for d in engine.decks), "disconnect"
                )
                for endpoint in endpoints:
                    endpoint.unlink(missing_ok=True)  # Our terminated process owned these sockets.
                process = subprocess.Popen(args, stdout=output, stderr=output)
                until(
                    lambda: all(d.status == Status.EMPTY for d in engine.decks),
                    "restart remains empty",
                )
                sleep(0.2)
                assert all(d.track is None for d in engine.decks), "Reconnect replayed a load"
                print(
                    "Pinned xwax: two decks, decode confirmation, failed/partial import, "
                    "reload, reconnect and restart passed"
                )
            except BaseException:
                print(log.read_text(errors="replace"))
                raise
            finally:
                if client:
                    client.close()
                    for worker in client._connections:
                        worker.thread.join(2)
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--importer", required=True, type=Path)
    options = parser.parse_args()
    smoke(options.engine.resolve(), options.importer.resolve())
