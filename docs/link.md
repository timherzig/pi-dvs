# Pro DJ Link

The optional Link adapter supports both directions on a wired DJ network:

- Browse a CDJ-hosted Device Library USB and download a selected track to a
  host-local cache, with early playback for supported AIFF files.
- Share the selected, mounted local Rekordbox USB with CDJs through the separate
  `pi-dvs-link` helper. CDJs play the original audio from that USB.

The desktop transport is silent unless connected to the native xwax engine
(Linux/ALSA on the Pi, or the optional macOS/Core Audio development backend).
Sharing to physical CDJs produces audio on the CDJs, independently of that engine.

## Build and run

Use a dedicated Ethernet interface connected to the same switch as the players.
The helper owns Pro DJ Link discovery, dbserver and NFS ports; quit rekordbox LINK
and other Link exporters on that interface before starting it. Source USBs are
read-only to pi-dvs; no files are exported back to a USB.

The helper is a separate GPL-2.0-or-later executable, built from the source under
`scripts/link` and pinned rbxport revision
`7fb4dad3f88a2cc0cecec0e718b4dde408fd7448`. Its compatibility patch is applied by
`build.sh`; an unexpected dependency revision or conflicting patch fails the build.
Install Rust with Cargo, then from the repository root:

```sh
make link-build
uv run --locked pi-dvs --library /Volumes/TIM \
  --link-interface en7 \
  --link-helper scripts/link/target/release/pi-dvs-link
```

Replace the USB root and interface with yours (`eth0` is a common Linux example).
If `CARGO_TARGET_DIR` is configured, use its `release/pi-dvs-link` binary instead.
The build uses the toolchain pinned in `scripts/link/rust-toolchain.toml`.
No administrator privileges or NFS system mounts are required.
To load into xwax, add the two `--xwax-sockets` paths described in [xwax.md](xwax.md).

**Open USB…** selects the local export to share. The **Music source** selector
switches browsing between that export and discovered CDJ USBs. Discovering another
source does not change the current view or interrupt sharing. A remote library is
read when selected; **Refresh** starts a fresh media generation. Selecting a remote
source leaves the chosen local USB available to the CDJs. On a CDJ, select the
computer source through **LINK**, browse its exported playlists or categories,
load a compatible track and press **PLAY**.

## Transfers, cache and media changes

CDJ reads use NFSv2 with the CDJ UTF-16 filename dialect. There is one outstanding
request at a time across all clients. Audio/cache materialization remains serialized,
but an uncached library can interleave requests between audio reads instead of
waiting for the entire track download. During full-file audio preparation, catalog reads can use half of the paced
request budget. AIFF transfers attempted in progressive mode use at most one eighth
to protect audio that may already be playing; unsupported AIFF layouts retain this
conservative reservation while falling back to full-file loading. They regain the full budget afterward. Transfer deadlines account for their minimum reserved rates. READ blocks are 1,280 bytes, paced at a ceiling of 256 KiB/s; retries use the same
transaction ID and also obey pacing. Per-request retries and whole-operation
limits prevent indefinite network waits. A 2.46 MB MP3 took about 11 seconds in
the original two-player hardware trial. Larger files take proportionally longer;
supported AIFF files can start playing while this retrieval continues.

On the Mac/CDJ-900 hardware setup, opening the second CDJ's uncached library
while downloading a long MP3 from the first took 12.2 seconds after correcting
scheduler wake-ups, versus 62.8 seconds before that correction. The library
became browsable before the audio download finished. This verifies interleaving
on that setup, not instantaneous imports or Raspberry Pi throughput. MP3 files
still download completely before xwax loads them.


With the current xwax build, 44.1 kHz, stereo, 16-bit PCM AIFF loads after ten
seconds of audio have been decoded (or the whole audio portion for a shorter
track). At the conservative download pace this normally takes about seven to ten
seconds plus catalog/network overhead. No lossy conversion is introduced: the
importer preserves the PCM sample values and changes only byte order for xwax.
Other formats/layouts retain complete-file loading. Downloads remain serialized;
a second new track waits while the first transfer finishes. Source-library reads
can progress during that wait; this does not promise instant catalog loading.
Superseded local serving catalogs are retired on reconnect while cached deck
audio remains protected.

The deck timeline shows decoded, playable audio separately from the playhead;
the percentage text reports bytes downloaded. The total duration stays fixed.
Seeking or running beyond the available prefix produces silence and a Buffering
status; the app does not slow the record or fabricate samples. Normal vinyl
positioning and xwax's motion protection still apply. A complete cache entry is
published only after final source/size/hash checks. During an unfinished import,
USB removal cancels the producer and displays an error; only already buffered
audio remains available. Closing the GUI also cancels unfinished downloads.
Private prefixes stay retained while the separate engine owns their descriptors.
A dead producer times out after fifteen seconds without progress.

Both the Python app and native engine/importer must be updated for this feature;
an older engine rejects the STREAM command without replacing its current track.

Serving uses a separate per-player budget selected for each file. The tested
44.1 kHz/16-bit PCM files use 256 KiB/s. Known PCM formats use their stereo data
rate; MP3/AAC use a known encoded bitrate. The nominal rate plus 40% is bounded
between 256 and 512 KiB/s; unknown metadata retains 512 KiB/s. This is a throughput
policy, not a guarantee for high-speed playback. A higher-bitrate file does not
raise the budget of every other file in the library.

The helper preserves complete requested READ blocks, charges retransmits, and
accumulates no burst credit while idle or changing files. Smaller replies caused
audible distortion on the CDJ-900 and are not used for serving. Mount and browsing
services use separate threads; at 256 KiB/s a maximum-size READ can delay another
request on the NFS socket by about 247 ms. Shutdown interrupts pacing.

Files are published atomically only after size, identity and SHA-256 checks.
Existing verified cache entries are hashed before reuse. A CDJ's sparse READ
attributes are accepted only with a matching file ID, followed by a fresh full
LOOKUP. Missing files, stale handles, source changes and cancelled jobs never
publish partial audio. The source database is checked before and after preparing
remote audio, and its stale record size is not trusted over NFS file metadata.

`--link-cache` selects a host-local cache; its default is Qt's application cache
under `link`. `--link-cache-mib` sets the audio quota (default 2,048 MiB). Least
recently used, unpinned audio can be evicted. Loaded decks, queued loads and
submitted xwax loads retain their files. An exclusive ownership lock prevents a
second pi-dvs instance from using the same cache until the first instance's
workers have stopped. Use a local disk, not either source USB or a network share.
Artwork and helper logs are separate from the audio quota.

A CDJ USB STOP/removal or player timeout cancels that media generation and its
unfinished imports/downloads. Already loaded cached audio remains available to
the engine. Reinsertion creates fresh identities even when paths and export IDs
are reused. A selected source is reimported automatically; a new source does not
steal the view. For the selected local USB, pi-dvs watches mount/database identity,
stops serving after removal or change, and reimports when the same path returns.
The OS must mount that drive; discovering arbitrary new local mount paths remains
part of the general USB/appliance milestone. Choose a differently named mount
with **Open USB…**.

The helper restricts access to catalog-listed audio and bounded analysis/artwork
assets inside the selected USB. Root, database and file identities are checked
again on access, including cached READ retries. Reusing a transaction ID with
different arguments cannot replay an unrelated audio block. New media generations
use new NFS handles; an old handle cannot silently resolve to a replacement track.
The helper is supervised off the GUI thread, restarts after exit, missed
heartbeats or a terminal network failure, and receives the current catalog again.
After an Ethernet adapter reconnect, it rediscovers the interface's current
address. On macOS, an idle-sleep assertion stays active for the Link session,
including helper restarts, and is released when the session ends. The display can
sleep; closing the lid, explicit sleep and low battery can still suspend the Mac.
Keep the lid open while serving. This does not change system power settings.
See [Apple's assertion behavior](https://developer.apple.com/documentation/iokit/kiopmassertiontypepreventuseridlesystemsleep).
Broken command pipes and shutdown are bounded. A helper restart invalidates
remote media and may require reloading the computer source on a CDJ.

## Compatibility and verification

The initial hardware trial used two original CDJ-900 players with firmware 4.32,
one CDJ USB and one Mac USB. Both played the Mac-hosted AIFF through its normal end
while ten paced MP3 downloads from the CDJ USB completed with identical hashes.
Physical CDJ USB STOP/removal cancelled an active download without publishing a
partial file. Reinsertion on the same running helper restored all 988 remote
tracks automatically, and a fresh download matched its expected hash. Cached
pi-dvs deck files survived both that cycle and Mac USB eject/reinsert. Returning
the Mac USB restored all 991 shared tracks automatically without refreshing or
restarting the app, while the selected CDJ library view remained selected.
An Ethernet unplug/replug test also restored sharing and remote imports
without restarting the app, preserving both cached deck files.
A subsequent release-build run completed ten exact-hash downloads, but macOS idle
sleep then removed the Ethernet interface and interrupted both players before
track end. The added sleep assertion held the Mac awake in later tests, but
512 KiB/s serving still produced a separate stall with no downloads running.
A stalled player's network latency stayed high after playback stopped; rebooting
that player restored its response. The Mac continued answering sparse READs
promptly. The underlying packet-delivery/player failure has not been established.

Reducing full-reply serving to 256 KiB/s passed three subsequent full 3:39-track
checks: one CDJ, both CDJs, and both CDJs during ten fresh paced downloads. All ten
downloads had matching hashes and took about 11.2 seconds each. The user confirmed
normal-speed, continuous audible playback to the end in all three runs; measured
player network responses stayed around 1 ms. Both players were healthy before
the simultaneous trials. All 991 files on the tested Mac USB were 44.1 kHz/16-bit
AIFF. Higher-bitrate formats, WIDE/high positive pitch, and longer performance
sessions remain unvalidated. At +100% even this PCM stream needs more than the
256 KiB/s budget; this compatibility policy is for nominal playback, not that
range. The fix does not transcode or resample to reduce bandwidth.

Audio is served unchanged, without transcoding or resampling. Track bitrate
metadata uses the imported value even when no optional database backend is
present; a missing fallback previously advertised zero for PCM AIFF and caused a
misleading VBR label. The metadata regression checks the actual wire response.

The CDJ-900 serving adapter advertises MP3, AAC/M4A, WAV and AIFF, omitting FLAC.
Encoding support still depends on the player. Device Library and OneLibrary can
feed local serving; remote retrieval currently reads `export.pdb` only. CDJ covers
are fetched after a deck confirms its track, without delaying audio readiness.
The loaded deck and its browser row update together. Other tracks retain placeholders
until loaded. Missing or damaged covers do not prevent playback.

Remote JPEG/PNG covers prefer the `_m` variant, fall back to the base image and
undergo actual pixel decoding on a worker. Retrieval uses the same paced queue,
a 512 KiB file limit and an eight-second cancellation budget. New audio loads
cancel pending covers first. The remote cover cache is limited to 64 MiB and
512 images; covers displayed by loaded decks stay pinned. USB removal preserves
already cached covers; reconnects use fresh source identities. Local USB artwork
keeps the limits described in [the import guide](rekordbox.md).

Analysis/artwork are provided to CDJs when valid files are present; this is not a
complete rekordbox replacement.
A separate CDJ-to-host test with the Mac USB absent imported 988 tracks into a
fresh cache. Mii's 2,458,167-byte MP3 loaded in 12 seconds with the known SHA-256;
a second 8,821,684-byte track downloaded in 40.6 seconds during playback. The user
confirmed uninterrupted sound through Mii's normal end. Audible output in this
test used a private native Mac player on the file prepared by the real controller;
the shipping Mac demo remains silent. This does not validate xwax/PX5 output.
The real CDJ cover was also retrieved and visually checked in the app.

Other player models/firmwares, simultaneous rekordbox exporters, Raspberry Pi
performance, PX5 routing and vinyl-driven audio need separate hardware validation.

```sh
make check       # Python transport, lifecycle, real subprocess and QML tests
make link-test   # loopback CDJ clients, concurrent reads, metadata and stale handles
make package     # install and open the Python wheel in a fresh environment
```

Automated fixtures are synthetic. Tests include lost/duplicate/malformed packets,
wrong peers, bounded retries and cancellation, media replacement with reused IDs,
cache eviction and ownership, stale imports, helper crashes and blocked stdin,
QML source selection, and loaded-file protection. Hardware checks must additionally
exercise audible playback on both players, USB STOP/removal/reinsertion on the CDJ,
and local USB eject/reinsert while retaining cached pi-dvs deck audio.

The Python wheel does not contain the GPL helper or its binary. Distributing a
helper binary requires its corresponding source and notices; see
[scripts/link/NOTICE](../scripts/link/NOTICE) and its `COPYING` file.
