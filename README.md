# pi-dvs

A small standalone digital vinyl system for a Raspberry Pi, Xone PX5 mixer,
and Serato NoiseMap control vinyl. The first milestone is a **silent desktop
demo**: browse a searchable sample library and load two independent decks.

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
- **Play / Pause** advances a simulated timer. **Unload** clears a paused deck.
- Pause a playing deck before loading another track or unloading it.
- Search for **Café** using `cafe`, or for **Untitled** to see the artwork fallback.
- Load **Archive Tape** to exercise a failed load, then load another track to recover.

The eight tracks and four SVG covers are original demo fixtures. No music is
bundled and no audio is produced. Play/Pause tests interface behavior; it does not
decode files, read timecode, or connect to an audio device. Search is a flat list;
playlists and real Rekordbox imports are follow-up work.

## Development

```sh
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

Tests cover independent decks, pending-load replacement/cancellation, failures and
recovery, playback protection, search, missing artwork, and real QML button/search
bindings. UI tests use Qt's offscreen software renderer. CI runs these checks on
macOS and Linux; audio performance and real-device behavior require later hardware
tests. `uv build` packages the QML and demo assets into the wheel and source archive.

```text
src/pi_dvs/
  app.py              startup and composition
  model.py            immutable track and deck values
  library.py          demo catalog and metadata search
  engine.py           deterministic, silent two-deck simulation
  presentation.py     Qt models, actions and timer
  ui/                 QML interface
  data/               demo metadata and original artwork
tests/                behavior tests and a QML interaction test
```

The engine and library contain no Qt or audio-device code. The GUI passes elapsed
time into the demo engine and displays snapshots; it does not own deck state.
A real xwax integration must report the engine's confirmed state instead of
assuming a sent load command succeeded. There is deliberately no speculative
plugin framework or production audio adapter yet.

For a future USB reader, keep mounting/hotplug separate from parsing. Traditional
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

[Waxcode](https://www.waxcode.co/) and its
[xwax fork](https://github.com/mhallrp/waxcode-xwax) are reference projects. No
Waxcode source or binary is included in this demo. Engine selection and PX5 audio
configuration still need validation.

## License

Project code and demo fixtures: Apache-2.0, see [LICENSE](LICENSE).
Qt/PySide is a separate dependency under its own license terms.
