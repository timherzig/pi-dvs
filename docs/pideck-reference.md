# PiDeck implementation reference

Inspected **21 October 2026**. PiDeck is an independent xwax-based Raspberry Pi
DVS project. Use it as implementation precedent for pi-dvs, not as a substitute
for testing our engine, PX5, OS and simultaneous workload.

## Sources and evidence

- [Project website](https://pideck.com/): reports Pi 3 Model B testing and a
  USB-stick/touchscreen/control-vinyl workflow. This is the project's report,
  not a hardware run performed by us.
- [Setup scripts at a9ca279](https://github.com/pideck/pideck/blob/a9ca2793ff020b7ba605792114d5e7decdc51fe7/): pinned revision inspected for this note.
- [xwax fork at d7d20fe](https://github.com/pideck/xwax/tree/d7d20feb9c2e8e1502c056fe2f095d98376f863f):
  latest default-branch commit observed is dated 10 June 2018. We inspected recent
  commit history, not a complete diff against our pinned upstream xwax 1.10.
- [Distro at 26ffeaa](https://github.com/pideck/pideck-distro/tree/26ffeaaa4184c6c6faf1084a3ce845c7a25e4f01):
  historical Debian image/build reference; its README uses a Stretch repository.
  The website describes Jessie. Neither is our current ARM64 deployment recipe.

## Hardware inference

PiDeck provides direct precedent for DVS on a Pi 3, and its actual launcher
configuration includes two-deck paths. That makes a **Pi 4 Model B with 4 GB a
credible budget implementation/test target**. Pi 5 is optional processing headroom,
not an established minimum. This is an engineering inference, not a measured
CPU/RAM budget or a Pi 4 qualification.

The [soundcard matrix](https://github.com/pideck/pideck/blob/a9ca2793ff020b7ba605792114d5e7decdc51fe7/soundcards.md) lists known-working multideck interfaces.
More concretely, [cards_autodetect](https://github.com/pideck/pideck/blob/a9ca2793ff020b7ba605792114d5e7decdc51fe7/cards_autodetect) passes two `-a` device
arguments for Audio 4/6/8 DJ, Hercules Mk2, Conectiv and other configurations.
This establishes implemented two-deck routing; it does not establish sustained
performance for every listed interface or our PX5's 10-input/10-output path.

Our Qt interface, Rekordbox imports, artwork, NAS and bidirectional Pro DJ Link
add work absent from the simple launch/mount flow inspected here. Measure peak
process memory, per-core CPU, thermal throttling, load times and audio underruns
under concurrent activity. Average CPU and generic benchmark ratios alone do not
establish realtime reliability. See [hardware validation](hardware.md) and the
[compact appliance design](compact-pi-appliance.md).

## Audio routing and realtime setup — #4

The [launcher](https://github.com/pideck/pideck/blob/a9ca2793ff020b7ba605792114d5e7decdc51fe7/pideck) defaults to ALSA at 48 kHz and starts xwax with memory
locking (`-k`), realtime priority (`-q 89`) and a device-specific buffer setting.
It also contains a JACK path. These demonstrate the deliberate audio scheduling
and configuration behind the small-board design; they are not universal settings
or physical latency measurements.

[T6.asound.conf](https://github.com/pideck/pideck/blob/a9ca2793ff020b7ba605792114d5e7decdc51fe7/T6.asound.conf) uses `dsnoop` for shared capture, `dmix` for
playback, `asym` for duplex and `plug` channel tables to expose stereo pairs.
Use the structure as a reference when evaluating PX5 sharing/routing. Establish
our actual channel map, sample formats, period/buffer sizes and conversion costs;
do not copy its channel numbers, IPC keys or buffer constants into a PX5 recipe.
Do not raise priority to 89 without checking the target's scheduling/IRQ behavior.

Retain our [pinned upstream engine and confirmed-state protocol](xwax.md).
PiDeck's fork is not a drop-in replacement for the pi-dvs control extension.

## Guest USB lifecycle — #6 and #18

[usbmount](https://github.com/pideck/pideck/blob/a9ca2793ff020b7ba605792114d5e7decdc51fe7/usbmount) mounts media read-only with restrictive mount flags,
allocates slots `/media/usb0` through `/media/usb7`, and requests an xwax rescan.
Its mount command uses low CPU/I/O priority; removal uses a lazy unmount and rescan.
These are concrete references for automatic insertion and source protection.

For pi-dvs, retain the boundary between OS mounting, source discovery and
[Rekordbox parsing](rekordbox.md). Mount slots are not stable source identities:
track source/media generations, reject stale work, and keep independent libraries
available. Lazy unmount does not prove a playing or loading track survives removal.
Use explicit eject/error states and test actual file/cache lifetime with xwax.
The eight mount slots do not prove eight independent libraries can be advertised
to physical CDJs. NAS access (#22) and Pro DJ Link (#8) remain separate adapters.

## Small touchscreen — #5 and #15

The launcher requests a **630×480** undecorated xwax window. The
[setup README](https://github.com/pideck/pideck/blob/a9ca2793ff020b7ba605792114d5e7decdc51fe7/README.md) describes auxiliary touchscreen buttons that send
simulated keypresses to xwax. This supports designing a useful compact display,
but does not prove our current Qt layout fits or needs the same rendering resources.

Use a purpose-designed seven-inch browser/deck-status layout and large touch
controls. Keep our UI actions connected to confirmed engine state rather than
simulated keyboard input. Test search keyboard, scrolling, source selection,
loading protection and error states at the selected resolution. See the
[compact display/workflow requirements](compact-pi-appliance.md#what-plug-and-play-requires-in-software).

## Startup and deployment — #7

The [setup README](https://github.com/pideck/pideck/blob/a9ca2793ff020b7ba605792114d5e7decdc51fe7/README.md) identifies a systemd soundcard setup service and
separate launcher/configuration files. The distro shows how these pieces were
assembled into a dedicated image. Use this separation as a reference for repeatable
appliance setup, with our own versioned services and explicit ownership.

Do not copy the launcher's broad `killall` calls (including Python), numeric-card
fallbacks, unconditional mixer-level changes, or overwriting `~/.asoundrc` from the
autodetection script. Manage only owned processes/configuration, identify the PX5
stably, recover from missing devices with bounded retries, and keep a healthy engine
running across GUI restarts. Startup should not unexpectedly start playback.
Use our modern 64-bit OS/dependencies and [release process](releasing.md), rather
than installing the historical PiDeck image.

## Reuse boundary

No PiDeck code is vendored or executed by this documentation change. Before copying
code, inspect the relevant file/package's license and preserve its attribution;
do not assume every repository or script has the same license. Keep the existing
application/engine licensing and packaging boundary intact.
