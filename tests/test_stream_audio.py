"""Progressive importer checks with synthetic PCM and a real growing file."""

import io
import json
import struct
import time
from threading import Thread

import pytest

from pi_dvs.stream_audio import (
    Layout,
    UnsupportedAudio,
    import_stream,
    inspect_aiff,
    write_state,
)


def aiff(frames=64, *, channels=2, bits=16, padding=0, tail=b"", rate=None):
    pcm = b"".join(
        struct.pack(">hh", (i * 13) % 65536 - 32768, (i * 7) % 65536 - 32768) for i in range(frames)
    )
    common = struct.pack(">hIh", channels, frames, bits)
    common += rate or bytes.fromhex("400eac44000000000000")
    body = b"AIFF" + b"NAME\0\0\0\x03abc\0" + b"COMM" + struct.pack(">I", 18) + common
    sound = struct.pack(">II", padding, 0) + bytes(padding) + pcm
    body += b"SSND" + struct.pack(">I", len(sound)) + sound + bytes(len(sound) % 2) + tail
    return b"FORM" + struct.pack(">I", len(body)) + body, pcm


def session(tmp_path, data):
    layout = inspect_aiff(data, len(data))
    assert isinstance(layout, Layout)
    descriptor = tmp_path / "track.pidvs-stream"
    descriptor.write_text(json.dumps(layout.to_json()))
    source = tmp_path / "audio.aiff"
    source.write_bytes(data[: layout.offset])
    write_state(tmp_path, layout.offset, "loading")
    return layout, descriptor, source


def worker(descriptor, output, **kwargs):
    errors = []

    def run():
        try:
            import_stream(descriptor, output, **kwargs)
        except Exception as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    return thread, errors


def until(condition):
    deadline = time.monotonic() + 2
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert condition()


def test_growing_file_emits_exact_frames_waits_at_eof_and_final_verification(tmp_path):
    data, pcm = aiff(tail=b"ANNO\0\0\0\x04test")
    layout, descriptor, source = session(tmp_path, data)
    output = io.BytesIO()
    thread, errors = worker(descriptor, output)
    with source.open("ab") as stream:
        stream.write(data[layout.offset : layout.offset + 7])
        stream.flush()
        write_state(tmp_path, layout.offset + 7, "loading")
        until(lambda: len(output.getvalue()) == 4)
        assert thread.is_alive()  # Partial frames and temporary EOF are not completion.
        stream.write(data[layout.offset + 7 :])
        stream.flush()
        write_state(tmp_path, len(data), "loading")
        until(lambda: len(output.getvalue()) == len(pcm))
        assert thread.is_alive()  # Even all PCM is not final source verification.
        write_state(tmp_path, len(data), "complete")
    thread.join(1)
    assert not thread.is_alive() and not errors
    assert output.getvalue() == b"".join(pcm[i : i + 2][::-1] for i in range(0, len(pcm), 2))


def test_source_failure_after_pcm_and_producer_death_are_bounded(tmp_path):
    data, _ = aiff()
    layout, descriptor, source = session(tmp_path, data)
    source.write_bytes(data)
    output = io.BytesIO()
    write_state(tmp_path, len(data), "loading")
    thread, errors = worker(descriptor, output)
    until(lambda: len(output.getvalue()) == layout.frames * 4)
    write_state(tmp_path, len(data), "failed", "USB disconnected")
    thread.join(1)
    assert not thread.is_alive()
    assert len(errors) == 1 and "USB disconnected" in str(errors[0])
    write_state(tmp_path, len(data), "loading")
    thread, errors = worker(descriptor, io.BytesIO(), stale=0.05)
    thread.join(1)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], TimeoutError)


def test_header_prefixes_padding_and_unsupported_formats():
    data, _ = aiff(padding=3)
    layout = inspect_aiff(data, len(data))
    assert layout.frames == 64
    assert layout.offset == 69
    for end in range(12):
        assert inspect_aiff(data[:end], len(data)) is None
    for options in ({"channels": 1}, {"bits": 24}, {"rate": b"\0" * 10}):
        data, _ = aiff(**options)
        with pytest.raises(UnsupportedAudio):
            inspect_aiff(data, len(data))
    with pytest.raises(UnsupportedAudio):
        inspect_aiff(b"FORM\0\0\0\x04AIFC", 12)
    data, _ = aiff()
    with pytest.raises(UnsupportedAudio, match="FORM"):
        inspect_aiff(data, len(data) + 1)


def test_committed_prefix_and_descriptor_cannot_claim_missing_audio(tmp_path):
    data, _ = aiff()
    layout, descriptor, _ = session(tmp_path, data)
    write_state(tmp_path, len(data), "complete")
    with pytest.raises(ValueError, match="missing"):
        import_stream(descriptor, io.BytesIO())
    write_state(tmp_path, layout.offset, "complete")
    with pytest.raises(ValueError, match="verified"):
        import_stream(descriptor, io.BytesIO())
    value = layout.to_json()
    value["frames"] *= 1000
    descriptor.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="exceeds"):
        import_stream(descriptor, io.BytesIO())
