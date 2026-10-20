# Optional xwax connection

The default desktop transport is a silent simulation. Real mode connects to two
Unix sockets owned by a separately started Linux engine. GUI and engine must see
the same audio paths. This integration does not manage processes, restore tracks
automatically or provide a Mac-to-Pi network bridge.

## Pinned upstream engine

The engine is [upstream xwax 1.10](https://xwax.org/releases/xwax-1.10.tar.gz),
with the focused pi-dvs headless/control extension in `scripts/xwax/`. It does
not use the Waxcode fork. The archive SHA-256 is
`589144364d0fea2cc7cbbc21ded25fd376c4c71819a126b8f5864e76eaebcdf3`.

`build.sh` verifies that archive, applies `confirmed-state.patch` without fuzzy
matching, copies `remote.c`/`remote.h`, and records the source version and extension
hashes beside the binary. The container base is pinned by digest. OS package
updates can change build dependencies; this is a repeatable source/build
procedure, not a claim of byte-identical binaries across dates or architectures.
Unmodified upstream and Waxcode binaries do not implement the `DVS2` contract.

On Ubuntu 24.04, dependencies are `build-essential`, `pkg-config`, `libsdl2-dev`,
`libsdl2-ttf-dev`, `libasound2-dev`, `ffmpeg`, `curl`, CA certificates, `patch`,
and Python 3 for the progressive importer and smoke. SDL remains a link dependency even in headless mode.
No new Python runtime dependency is required.

```sh
# Linux; output directory must not exist. No system installation is performed.
sh scripts/xwax/build.sh "$PWD/build/xwax"
```

Upstream xwax (Mark Hills) and the pi-dvs patch/extension are GPL-3.0. See
[`NOTICE`](../scripts/xwax/NOTICE) and [`COPYING`](../scripts/xwax/COPYING).
The Python application retains its existing Apache-2.0 license; its wheel
contains no xwax source or binary. Retain the engine's license, attribution and
corresponding source plus extension when redistributing an engine build.

## Run without audio hardware

Each socket option precedes its deck. Use a private, user-owned directory; sockets
have owner-only permissions. Socket mode requires `--no-interface` and disallows
native MIDI controllers so the callback is the sole writer of player state.

```sh
mkdir -p "$HOME/.cache/pi-dvs"
chmod 700 "$HOME/.cache/pi-dvs"
build/xwax/xwax --no-interface --rtprio 0 --protect \
  --import "$PWD/build/xwax/import" \
  --socket "$HOME/.cache/pi-dvs/a.sock" --dummy \
  --socket "$HOME/.cache/pi-dvs/b.sock" --dummy
```

On the same Linux host:

```sh
uv run --locked pi-dvs \
  --xwax-sockets "$HOME/.cache/pi-dvs/a.sock" "$HOME/.cache/pi-dvs/b.sock" \
  --library /path/to/mounted/usb
```

Without `--library`, real mode starts with an empty browser and **Open USB…**.
`--demo` and `--xwax-sockets` are mutually exclusive. Omitting `--xwax-sockets`
retains the simulator, including when browsing a real USB.

The engine refuses to replace existing socket files. After an abrupt exit,
remove its stale sockets only after confirming that the owning engine stopped.
Use one controlling app: a new client replaces the prior connection on that deck.

Dummy decks exercise import and communication. They have no audio callbacks,
playback or timecode decoding. For real audio, native ALSA devices replace the
dummies. PX5 channel mapping, realtime privileges, RAM locking, buffer sizes and
physical Serato vinyl behavior need hardware validation. `--rtprio 0` is for the
hardware-free smoke, not a tuned performance configuration.

## Confirmed state and native transport

Each deck has a background connection with serialized commands and immutable
snapshots. File preflight and socket I/O run off the GUI thread. Replies have a
500 ms deadline, status polls every 100 ms, and load confirmation has a 120 second
limit. The GUI never extrapolates real playback position. These intervals affect
control feedback, not the audio processing buffer or vinyl response.

- **Waiting for engine** means a command is pending. An ACK is not load success.
- **Loading** means native decoding is in progress. **Ready** requires successful
  importer exit with nonempty PCM. **Playing** means native motion, not proof of
  audible output or physical needle contact.
- Import failures, including PCM followed by a decoder error, remain errors. A
  readable local file is only preflight. As in upstream, partial PCM may be
  available to native playback during import; it is never reported as confirmed
  success until the importer finishes successfully.
- Missing sockets, stopped audio callbacks, timeouts and disconnects disable
  mutations. Last known values can remain visible, labeled unavailable.
- Reconnect first reads state and adopts the actual track, position and mode.
  Pending commands are discarded, never replayed. File preflight carries a
  connection generation so delayed USB checks cannot act on a later session.
- Real mode has no simulated needle/platter, Play/Pause, seek, loop or mode controls.
  Load and reconnect preserve native transport state; they do not send mode changes.

The UI reports **Vinyl tracking** when native timecode control is connected,
including whether an absolute position is unavailable. Upstream can continue
from speed information without a valid absolute timestamp. At the record's safe
limit it disconnects timecode and can continue internal playback; the UI reports
**Internal playback · Vinyl control disconnected**. Returning the needle does
not automatically reconnect it. This extension deliberately preserves that
[upstream behavior](https://xwax.org/guide.html); the absolute-position and safe
runout product requirements remain separate work in issue #12.

Mutations require `--protect`. The app checks fresh status; the callback checks
again after its current timecode update, using upstream's `abs(pitch) > 0.01`
criterion. Reverse motion is protected too. Importing, pending and unavailable
states also disable app changes. This threshold is not a needle-contact sensor;
signal dropout behavior remains a hardware requirement in issues #4/#13.

## Audio/control separation

The extension adds no audio buffer, DSP stage, resampler or scheduling wait.
Native xwax still captures timecode, decodes it and renders directly through its
existing device callbacks. Socket service uses ordinary threads, outside the
realtime device/controller loop.

A single-slot atomic mailbox transfers prepared track references to the audio
callback. It does bounded work: recheck speed, swap a pointer if safe, publish a
result. Old tracks are released by the control thread after acknowledgement;
allocation, decoding, reference retirement and sockets stay outside the callback.
The control thread never takes the player's audio-source spinlock, so a slow
client cannot make native `spin_try_lock` fall back to silence.

Three small telemetry structs transfer position/mode to the socket thread using
lock-free integer exchanges. They contain no PCM. There is one writer and one
reader, each owning a separate slot. A stalled reader cannot delay the writer.
Importer result and decoded PCM length use release/acquire publication. The rig
lock serializes shared track-cache operations exclusively on ordinary threads.
Seek logging and ALSA xrun logging are replaced by telemetry/counters; recurring
log output is not added to audio processing.

## DVS2 contract

Only these newline-terminated UTF-8 commands are supported:

```text
DVS2 LOAD <32 lowercase hex request ID> <absolute path>
DVS2 STREAM <32 lowercase hex request ID> <total seconds> <absolute descriptor path>
DVS2 UNLOAD <32 lowercase hex request ID>
DVS2 STATUS
DVS2 METRICS
```

Paths are unquoted and last, preserving spaces and Unicode. NUL, CR and newline
paths are rejected. Commands including newline are at most 1,023 bytes. Client
reply buffering is bounded to 8 KiB, preserving fragmented/coalesced lines and
rejecting malformed numbers, flags, paths and versions. Partial/failed native
writes disconnect instead of waiting for a slow reader.

Mutations reply `DVS2 ACK <id> <result>`: `ACCEPTED`, `BUSY`, `LOCKED`,
`UNPROTECTED`, `INVALID`, or `ERROR`. Status is authoritative:

```text
DVS2 STATE <id|-> <result> <state> <active> <protected> <timecodeControl> <positionKnown> <elapsed> <duration> <pitch> <path>
```

Result is `NONE`, `PENDING`, `OK`, `LOCKED`, or `ERROR`; state is `EMPTY`,
`IMPORTING`, `READY`, or `ERROR`. Flags are 0/1; times are seconds; pitch is signed
relative speed. Duration grows during import. Empty decks retain the final space
with an empty path. A request's ID/result survive reconnect, not engine restart.
A rejected ACK does not overwrite an in-flight request. A matching ID, final
result and expected track/empty state confirm the command, including same-path
loads. The client never retries an uncertain mutation.

Progressive STREAM loads use a private `.pidvs-stream` descriptor and the bundled
standard-library Python AIFF importer. Supported input is stereo 16-bit PCM at
44.1 kHz. The control thread keeps the previous track until at least ten seconds
(or a shorter track's full duration) have decoded, then requests the same
motion-protected callback handoff as LOAD. Streaming decks report:

```text
DVS2 STREAM_STATE <id|-> <result> <state> <active> <protected> <timecodeControl> <positionKnown> <elapsed> <total duration> <pitch> <decoded duration> <path>
```

`STREAMING` confirms early attachment; `READY` requires successful final import
and matching decoded duration. A failed/truncated import reports `ERROR`, even
when it emitted PCM first. The importer waits at temporary EOF outside the audio
callback; its producer timeout is bounded. A stopped streaming deck may be
unloaded or replaced. Total duration never follows the growing buffer. The
progressive smoke checks early attachment, growing prefixes, short tracks,
stopped unload and terminal source failure against the actual native binary.

`DVS2 STALE` disables app mutations when real audio callbacks stop advancing for
500 ms. Dummy devices explicitly bypass that check. `DVS2 METRICS` replies with
`DVS2 METRICS <callback count> <capture xruns> <playback xruns>`. Xrun counters
count ALSA's reported `EPIPE` recoveries; zero counters do not prove inaudibility,
correct routing or low latency. `DVS2 UNSUPPORTED` rejects other commands,
including digital `PLAY`.

## Verification and hardware measurements

```sh
make check       # Contracts, offscreen QML and existing regressions
make package     # Installed wheel, resources and QML
make xwax-smoke  # Docker: actual pinned Linux binary and native callback probe
```

The smoke uses two dummy decks and a redistributable one-second WAV fixture.
It verifies both imports, independent unload, corrupt/missing/partial failures,
recovery, same-path reload, reconnect adoption and restart without replay.

The native probe links the production objects and feeds synthetic quadrature
samples through the real timecoder/player with the decoded fixture. It checks
fresh forward/reverse motion protection, deferred track retirement and native
mode reporting. During callbacks, linker wrappers fail on heap allocation/free,
blocking locks, poll, socket I/O, read/write or stdio logging. It renders with
control disabled, idle, flooded and with a client not reading; verifies audio is
produced and no player-lock contention occurs; and prints callback wall-time
p50/p99/max. Timing values are diagnostic, not a flaky CI threshold or physical
latency estimate. CI requires this Linux job plus the Python/platform matrix.

For Pi/PX5 acceptance, record sample rate, actual ALSA buffer/period configuration,
engine/source hashes, realtime priority, CPU governor/temperature and channel map.
Use synchronized capture of timecode input and analogue output to measure response
to reproducible starts, stops, reversals and scratching. Report distributions and
worst case, not just a nominal buffer size. Repeat long playback runs with GUI
closed, normal polling, GUI/search/import load and a stalled client. Compare
capture/playback xrun counts before and after each run. Reduce native ALSA buffer
settings only while these measurements remain stable; the GUI adds no buffering
knob of its own.

Counter snapshots can be collected before launching and after closing the GUI
(the diagnostic connection would otherwise replace its deck connection):

```sh
PYTHONPATH=src python3 - "$HOME/.cache/pi-dvs/a.sock" "$HOME/.cache/pi-dvs/b.sock" <<'PY'
import socket
import sys
from pi_dvs.xwax.protocol import Connection
for path in sys.argv[1:]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        sock.connect(path)
        print(path, Connection(sock, 1).exchange(b"DVS2 METRICS\n"))
PY
```

Docker/dummy/probe results establish software behavior only. No physical PX5
latency, underrun rate, vinyl fidelity or Raspberry Pi performance is established
without that hardware run.
