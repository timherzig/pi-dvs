"""Real child-process lifecycle tests, without accessing a DJ network."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from threading import Event

import pytest

from pi_dvs.link.service import LinkService
from pi_dvs.rekordbox.records import ImportFailure

HELPER = r"""
import json, os, pathlib, sys, threading, time
root = pathlib.Path(__file__).parent
catalog = None
revision = -1

def read():
    global catalog, revision
    for line in sys.stdin:
        command = json.loads(line)
        with (root / "commands").open("a") as output:
            output.write(line)
        catalog, revision = command["catalog"], command["revision"]
    os._exit(0)

if not (root / "blocked").exists():
    threading.Thread(target=read, daemon=True).start()
while True:
    mode = (root / "mode").read_text() if (root / "mode").exists() else "healthy"
    if mode == "down":
        (root / "mode").unlink()
    if mode == "crash":
        (root / "mode").unlink()
        sys.exit(7)
    if mode == "bad":
        print("[]", flush=True)
    elif mode != "silent":
        print(json.dumps(dict(address="127.0.0.1", serving=catalog is not None,
            tracks=len(catalog["tracks"]) if catalog else 0, revision=revision,
            state='Down("en7 no longer has the address 169.254.112.228")'
                if mode == "down" else "Up { number: 17 }",
            players=[dict(address="127.0.0.1", mac=[1,2,3,4,5,6],
                number=1, usb=True, generation="one")])), flush=True)
    time.sleep(.05)
"""


def until(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert condition()


def helper(tmp_path):
    path = tmp_path / "helper"
    path.write_text(f"#!{sys.executable}\n" + HELPER)
    path.chmod(0o755)
    return LinkService("test", path, tmp_path / "cache")


def test_process_restart_republishes_catalog_and_invalidates_old_generations(tmp_path):
    link = helper(tmp_path)
    link._command = {"tracks": [1, 2]}
    link.start()
    try:
        until(lambda: "sharing 2" in link.status)
        media = link.sources.views()[0].media
        process = link._process
        (tmp_path / "mode").write_text("crash")
        until(lambda: media.cancelled.is_set())
        until(lambda: link._process not in (None, process) and "sharing 2" in link.status)
        replacement = link.sources.views()[0].media
        assert replacement.source_id != media.source_id
        assert not replacement.cancelled.is_set()
        commands = [json.loads(line) for line in (tmp_path / "commands").read_text().splitlines()]
        assert [command["catalog"] for command in commands] == [{"tracks": [1, 2]}] * 2
        # A silent live process must be replaced by the heartbeat watchdog.
        process = link._process
        (tmp_path / "mode").write_text("silent")
        time.sleep(0.1)
        with link._lock:
            link._last_report = time.monotonic() - 10
        until(lambda: "stopped reporting" in link.status)
        (tmp_path / "mode").unlink()
        until(lambda: link._process not in (None, process) and "sharing 2" in link.status)
    finally:
        process = link._process
        link.close()
        link._worker.join(5)
        assert not link._worker.is_alive()
        assert process.poll() is not None


def test_invalid_helper_message_is_rejected_and_process_reaped(tmp_path):
    link = helper(tmp_path)
    (tmp_path / "mode").write_text("bad")
    link.start()
    try:
        until(lambda: "failed" in link.status or "unavailable" in link.status)
        assert not link.sources.views()
    finally:
        link.close()
        link._worker.join(5)
        assert not link._worker.is_alive()


def test_shutdown_interrupts_full_command_pipe_and_retains_cache_until_exit(tmp_path):
    link = helper(tmp_path)
    (tmp_path / "blocked").touch()
    link._command = {"tracks": ["x" * 1024] * 1024}
    link.start()
    try:
        until(lambda: link._process is not None and link._last_report)
        time.sleep(0.35)  # pipe capacity is far smaller than the command
        process = link._process
        other = LinkService("test", tmp_path / "helper", link.cache_root)
        with pytest.raises(ImportFailure, match="another pi-dvs"):
            other.import_local(Path(__file__).parent / "fixtures/usb", "pdb", Event())
        started = time.monotonic()
        link.close()
        assert time.monotonic() - started < 0.1
        link._worker.join(5)
        assert not link._worker.is_alive()
        assert process.poll() is not None
        with other._lease.use():
            pass
        other.close()
    finally:
        link.close()


def test_network_down_snapshot_restarts_live_helper_and_rediscovers_media(tmp_path):
    link = helper(tmp_path)
    link._command = {"tracks": [1, 2]}
    link.start()
    try:
        until(lambda: "sharing 2" in link.status)
        media = link.sources.views()[0].media
        process = link._process
        # Captured hardware failure: heartbeats continue, but LinkExport is
        # permanently Down even after the interface address returns.
        (tmp_path / "mode").write_text("down")
        until(lambda: media.cancelled.is_set())
        until(lambda: link._process not in (None, process) and "sharing 2" in link.status)
        assert process.poll() is not None
        replacement = link.sources.views()[0].media
        assert replacement.source_id != media.source_id
        assert not replacement.cancelled.is_set()
        commands = [json.loads(line) for line in (tmp_path / "commands").read_text().splitlines()]
        assert [command["catalog"] for command in commands] == [{"tracks": [1, 2]}] * 2
    finally:
        link.close()
        link._worker.join(5)
        assert not link._worker.is_alive()


def idle_sleep_assertions():
    output = subprocess.check_output(["/usr/bin/pmset", "-g", "assertions"], text=True)
    return {
        re.search(r"\[(0x[0-9a-f]+)\]", line).group(1)
        for line in output.splitlines()
        if f"pid {os.getpid()}(" in line and 'named: "pi-dvs Pro DJ Link"' in line
    }


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS power assertions")
def test_link_holds_idle_sleep_assertion_across_helper_restart_and_releases_on_close(tmp_path):
    assert not idle_sleep_assertions()
    link = helper(tmp_path)
    link._command = {"tracks": [1]}
    link.start()
    try:
        until(lambda: "sharing 1" in link.status)
        assertions = idle_sleep_assertions()
        assert len(assertions) == 1, "Link streaming must prevent automatic idle sleep"
        process = link._process
        (tmp_path / "mode").write_text("crash")
        until(lambda: link._process not in (None, process) and "sharing 1" in link.status)
        assert idle_sleep_assertions() == assertions
    finally:
        link.close()
        link._worker.join(5)
        assert not link._worker.is_alive()
        assert not idle_sleep_assertions()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS power assertions")
def test_idle_sleep_assertion_is_released_on_supervisor_failure(tmp_path, monkeypatch):
    link = helper(tmp_path)

    def fail():
        assert len(idle_sleep_assertions()) == 1
        raise OSError("simulated supervisor failure")

    monkeypatch.setattr(link, "_supervise", fail)
    link.start()
    link._worker.join(5)
    assert not link._worker.is_alive()
    assert "simulated supervisor failure" in link.status
    assert not idle_sleep_assertions()
    link.close()


def test_non_macos_link_does_not_load_apple_frameworks(monkeypatch):
    from pi_dvs.link import power

    monkeypatch.setattr(power.sys, "platform", "linux")

    def unavailable(*args):
        pytest.fail("Apple frameworks must not be loaded on Linux")

    monkeypatch.setattr(power.ctypes, "CDLL", unavailable)
    with power.prevent_idle_sleep():
        pass
