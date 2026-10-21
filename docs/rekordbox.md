# Rekordbox USB import and browsing

Select an already-mounted media root containing `PIONEER/rekordbox`. The library
reader never mounts drives or writes to source media. It does not depend on the
volume name, a local rekordbox installation, an XML export, or a desktop
`master.db`. The optional [Pro DJ Link adapter](link.md) adds remote USB retrieval,
local serving and source lifecycle handling; OS mounting remains separate.

## Supported exports

| Export | Reader | Behavior |
| --- | --- | --- |
| Device Library `export.pdb` | Pinned `rekordbox-pdb` binary reader | Track metadata, artwork references, playlist folders and ordered entries |
| OneLibrary `exportLibrary.db` (formerly Device Library Plus) | SQLCipher 0.6.4, read-only private snapshot | The exported content/lookup/playlist schema, including nested folders |
| Both present | Auto prefers Device Library; explicit selector can switch | No merging of IDs or playlist contents; fallback is reported |

The PDB dependency is pinned to commit
`ee3bac2f22ca11a5ce61eea35f8cb951c246eaef` via a hash-locked source archive.
Before parsing, the application validates page sizes, page ownership, table
chains and row offsets, including cyclic and out-of-file links. Local adapters
handle the far-name album variant and the full 13-bit allocated-row count and partial final row group absent
from that dependency revision. Parsing and preflight use the same row-directory
decoder, including live rows beyond slot 511.

OneLibrary is encrypted SQLite, not a generic SQLite database. The reader opens
its snapshot with URI `mode=ro`, `immutable=1`, and `query_only=ON`, using the
public export interoperability key. No desktop database credentials are read.
Observed export durations are seconds: this was cross-checked against DeviceSQL
and audio metadata, rather than assuming the milliseconds described by one
reference. Unsupported schemas fail with an actionable re-export message.

These readers cover known Device Library and OneLibrary layouts. Unknown future
schemas, corrupt exports and unsupported playlist attributes are errors rather
than proof of universal compatibility. Database size is capped at 256 MiB.

## Tracks, artwork and browsing

Imported fields include title, artist, duration, album, genre, BPM, musical key,
source identity, original export ID, media-relative audio path, resolved local
file and cover art. Paths support Unicode, spaces and either slash convention.
Leading slashes refer to the selected media root. Parent traversal, host drive
letters, and symlinks escaping that root are rejected.

Recognized audio-file extensions are AIFF/AIF, WAV, MP3, M4A, AAC and FLAC.
Availability means a supported file exists and is readable, not that an engine
has decoded it. Loading reopens the file on a worker and rejects empty or removed
files. Decoder support for individual encodings, DRM and actual audio output must
be confirmed by the real engine in #3. The bundled WAV test fixture is decoded in
tests; AIFF metadata was checked during the real USB smoke test.

Playlist order and repeated track entries are preserved. Missing track IDs in a
playlist produce a warning. Missing audio remains visible but unavailable.
Playlist folders, empty playlists, artist/album/genre/key groups, five-BPM bands,
and all-track search are supported. Waveforms, cue/loop points, beat grids, My Tag,
play history and a full replica of every CDJ menu are not part of this change.

Available JPEG/PNG artwork is copied into Qt's local application cache directory
under `artwork`. The 240-pixel `_m` variant is preferred to the base cover. Pillow
checks that JPEG/PNG pixels decode on the import worker before accepting a cover;
a broken, oversized or unreadable preferred image falls back to the base image.
Covers are limited to 8 MiB encoded and 16,777,216 pixels decoded, then named by
content hash, with atomic publication and asynchronous QML loading. A placeholder
is used when neither candidate is usable. The cache can be
removed while the app is closed; it is rebuilt on import. Cache quota/eviction
for network audio is handled by the [Link cache](link.md).

## Lifecycle and Pro DJ Link

Importing uses immutable catalog snapshots and request generations. Cancellation
or a newer selection prevents stale publication; failures leave the current
catalog, search and decks intact. Media I/O runs outside the GUI thread in bounded
daemon workers, so a blocked device read does not hold the window open at exit.
Cancellation stops work between operations; it cannot interrupt a kernel read.

Track identity combines the source root and database revision with the export
track ID. A different export that reuses IDs cannot accidentally select an old
track. This is a mounted-source identity, not a universal USB serial number.

The parser stays independent of network discovery and OS mounting. The optional
[Link service](link.md) adds CDJ source discovery, media generations, paced retrieval
to a protected host cache, and serving through a separate GPL helper. Loaded decks
retain cached audio while new loads from disconnected media are cancelled. Without
Link enabled, the local-only importer retains its existing manual refresh behavior.

## Verification

`make check` runs type/lint checks, integration tests, offscreen QML interaction
tests and coverage. `make package` installs a wheel plus hash-locked dependencies
into a fresh environment and opens the packaged interface.

Fixtures include a genuine one-track DeviceSQL export from the MIT-licensed
upstream project, an independent synthetic DeviceSQL encoder, an encrypted
OneLibrary fixture with the actual consumed export tables, original PCM audio,
and original artwork. No music or metadata from the user's USB is bundled.
See `tests/fixtures/README.md` for provenance and regeneration.

Tests cover both formats, relocated/read-only source trees, Unicode/long strings,
playlist hierarchy/order/repeated entries, missing audio/artwork, corruption,
PDB deleted rows and live entries across 512/1,024 allocated slots, keyboard
loading before navigation, failed imports and cancellation races. The fixture
generator is included in the strict mypy gate.

Local smoke check on the supplied FAT32 USB: both formats yielded 991 tracks and
111 playlist/folder nodes; all 991 audio paths resolved and 938 tracks had artwork.
Imports took approximately 3–4 seconds in that run. This is one compatibility
sample, not a benchmark or a guarantee for all media. macOS 13 and Pi hardware
validation remain separate from the local Mac and CI checks. SQLCipher's pinned
wheels support macOS 11+ Apple Silicon and Linux ARM64; packaging still needs to
be exercised on each deployment target.

## References

- [Deep Symmetry DeviceSQL analysis](https://djl-analysis.deepsymmetry.org/rekordbox-export-analysis/exports.html)
- [rekordbox-pdb source and format specification](https://github.com/fragmede/rekordbox-pdb/tree/ee3bac2f22ca11a5ce61eea35f8cb951c246eaef)
- [pyrekordbox OneLibrary schema](https://pyrekordbox.readthedocs.io/en/latest/formats/onelibrary.html)
- [SQLCipher Python binding](https://pypi.org/project/sqlcipher3/0.6.4/)
