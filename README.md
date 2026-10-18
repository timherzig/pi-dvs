# pi-dvs

A small standalone digital vinyl system for a Raspberry Pi, Xone PX5 mixer,
and Serato NoiseMap control vinyl. The desktop app browses real Rekordbox USB exports and loads two independent
decks. Transport defaults to a **silent simulation**. An optional local Linux
connection uses a pinned, patched xwax engine; hardware routing is a separate milestone.

## Run on your Mac

Target: **macOS 13 or newer**, including the MacBook Pro M1 Pro. The application
runs natively on Apple Silicon. No mixer, Raspberry Pi, music files, or xwax
installation is needed for this demo.

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed
   (`brew install uv` if you already use Homebrew).
2. Open Terminal in this project directory (the folder containing `pyproject.toml`).
3. Run:

   ```sh
   uv run --locked pi-dvs
   ```

uv selects Python 3.12 from `.python-version`, downloads it if needed, and installs
the locked dependencies in a local `.venv`. First launch needs an internet
connection and downloads Qt; subsequent launches use the installed environment.
`uv run --locked pi-dvs --demo` is equivalent. Close the window to quit.

Qt is constrained to 6.10 because [that series supports macOS 13](https://doc.qt.io/qt-6.10/macos.html).
Do not update it past this series without rechecking the minimum macOS version.
A separate Python or Qt installation is unnecessary.

## Try the demo

- Search by title or artist; search ignores case and accents. Cmd+F focuses search;
  Escape or the clear button removes the query.
- Click **Load A** or **Load B** beside a track. Each deck moves from Loading to Ready.
- In **Simulated vinyl**, use **Start platter** and **Lower needle** for that deck.
  Both are needed for the silent playback timer to advance. There is no Play/Pause button.
- **Stop platter** or **Lift needle** holds the position. Starting/lowering again resumes
  there; each deck has its own controls.
- Loading, replacing, and unloading are blocked while the needle is down and the
  record is moving. Stopping the record is enough to allow a change, even with the
  needle down. A lifted needle also allows changes on a spinning platter.
- A finished track stays at its end. To start over in this demo, stop the record or
  lift the needle and reload the track. The platter/needle controls keep their state
  across load and unload.
- Search for **Café** using `cafe`, or for **Untitled** to see the artwork fallback.
- Load **Archive Tape** to exercise a failed load, then load another track to recover.

The eight tracks and four SVG covers are original demo fixtures. No music is
bundled and no audio is produced. The simulator uses constant forward speed and
explicit needle/platter inputs; it does not decode files, read timecode, detect a
physical needle, or connect to an audio device. Needle drops currently resume the
held position. [Absolute position, reverse motion, and scratching](https://github.com/timherzig/pi-dvs/issues/12)
will follow the real vinyl in a later milestone. [Reliable needle-up detection](https://github.com/timherzig/pi-dvs/issues/13)
is separate research for a possible stricter loading rule: silence or zero speed
alone does not distinguish a lifted needle from a stationary record. The bundled demo remains available alongside real USB imports.

## Browse your Rekordbox USB

Click **Open USB…** and choose the mounted drive's root folder (the one containing
`PIONEER`). Import runs in the background; **Cancel** keeps your current library.
You can also open a drive at startup:

```sh
uv run --locked pi-dvs --library /Volumes/TIM
```

The path is an example: any already-mounted supported export can be selected.
Use **Playlists** to browse exported folders and playlists in their saved order,
or browse **Artist**, **Album**, **Genre**, **BPM** (five-BPM bands), and **Key**.
**Back** moves up the hierarchy. **All tracks** sorts by title and keeps title/artist search across
the whole library; inside a playlist or category, search filters that view.
Category lists search their names. Search ignores case and accents.
Select a track and use **Load A/B**, or Ctrl+1/Ctrl+2. Audio files are checked again
before loading; missing or unsupported files have a reason and disabled load buttons.
Without `--xwax-sockets`, deck transport remains simulated and does not produce sound.

**Auto** uses traditional Device Library (`export.pdb`) first and falls back to
OneLibrary (`exportLibrary.db`) with a visible notice if necessary. The format
selector can switch the current drive to either library. Their records are never
merged, since the two exports can differ. **Refresh** rereads the active source;
a failed import preserves the last usable catalog and loaded decks.

The application reads source media only. Artwork is cached on the computer;
missing or undecodable covers use the existing fallback. See
[USB formats, limitations, and verification](docs/rekordbox.md) for details.

## Connect both directions over Pro DJ Link

An optional adapter retrieves tracks from a CDJ-hosted USB into a paced, protected
local cache and shares a selected local USB with both CDJs. Its source picker,
disconnect cancellation, fresh-media identities and helper recovery are integrated
with the existing library and deck controls. See [Link build, setup and testing](docs/link.md).

## Connect to xwax on Linux

Build and start the pinned engine, then select its two local deck sockets:

```sh
uv run --locked pi-dvs --xwax-sockets /path/to/a.sock /path/to/b.sock --library /path/to/usb
```

The application reports confirmed engine state and hides simulation controls.
A disconnect disables loading; reconnect reads the existing decks without
replaying commands. Unmodified upstream binaries do not provide the
required confirmed-import extension. See [engine setup and verification](docs/xwax.md)
for the exact revision, patch, dependencies, license and a hardware-free Linux
smoke check. PX5 audio routing, latency and vinyl behavior still need hardware tests.

## Development

```sh
make setup
make check
make package
```

Tests cover independent decks, pending-load replacement/cancellation, failures and
recovery, vinyl-driven transport, track-change protection, end-of-track behavior,
search, real USB import, nested playlists, missing artwork, and real QML button/search
bindings. UI tests use Qt's offscreen software renderer. CI runs these checks on
macOS and Linux; audio performance and real-device behavior require later hardware
tests. `make package` builds and smoke-tests an installed wheel with its QML and
demo assets. See [CONTRIBUTING.md](CONTRIBUTING.md) for coding standards and hooks,
and [the release workflow](docs/releasing.md) for CI/CD, promotion, and rollback.

```text
src/pi_dvs/
  app.py              startup and composition
  model.py            immutable track and deck values
  library.py          catalog, metadata search and playlist/category browsing
  rekordbox/          read-only DeviceSQL and encrypted OneLibrary adapters
  link/               paced retrieval, cache and supervised serving helper
  jobs.py             cancellable background media I/O
  engine.py           deterministic, silent two-deck simulation
  presentation.py     Qt models, actions and timer
  ui/                 QML interface
  data/               demo metadata and original artwork
tests/                behavior tests and a QML interaction test
```

The engine and library contain no Qt or audio-device code. The GUI passes elapsed
time into the demo engine and displays snapshots; it does not own deck state.
A real xwax integration must report the engine's confirmed state instead of
assuming a sent load command succeeded. The source-aware track values retain export IDs and media-relative paths for
remote retrieval. The optional `xwax/` adapter serializes commands and status
polling on background workers; Python stays outside the real-time audio path.

The USB reader keeps mounting/hotplug separate from parsing. Traditional
Rekordbox exports use `PIONEER/rekordbox/export.pdb`, while OneLibrary exports use
`exportLibrary.db`; a generic SQLite fixture does not prove USB compatibility.
See [the export format analysis](https://djl-analysis.deepsymmetry.org/rekordbox-export-analysis/exports.html).

## Next milestones

The follow-up tickets include acceptance criteria and dependencies:

1. [Read and search a real Rekordbox export](https://github.com/timherzig/pi-dvs/issues/2).
2. [Connect to a real xwax engine](https://github.com/timherzig/pi-dvs/issues/3).
3. [Validate Pi/PX5 audio with Serato vinyl](https://github.com/timherzig/pi-dvs/issues/4).
4. [Run on a Pi touchscreen](https://github.com/timherzig/pi-dvs/issues/5).
5. [Handle USB insertion/removal](https://github.com/timherzig/pi-dvs/issues/6).
6. [Boot and recover as an appliance](https://github.com/timherzig/pi-dvs/issues/7).
7. [Drive playback from absolute vinyl position](https://github.com/timherzig/pi-dvs/issues/12).
8. [Research reliable needle-up detection](https://github.com/timherzig/pi-dvs/issues/13).

[Upstream xwax](https://xwax.org/) 1.10 with a focused headless/control extension
provides the optional engine. The pinned source, audio/control separation and
verification are documented in [engine setup](docs/xwax.md).
The Python wheel contains no xwax binary; PX5 configuration still needs validation.

## License

Application code and demo fixtures: Apache-2.0, see [LICENSE](LICENSE).
The xwax engine patch is GPL-3.0; see [its notice](scripts/xwax/NOTICE).
The separate Pro DJ Link helper is GPL-2.0-or-later; see [its notice](scripts/link/NOTICE).
Qt/PySide is a separate dependency under its own license terms.
