# Budget hardware for a dedicated pi-dvs appliance

Research date: **20 October 2026**. Scope:
[#19](https://github.com/timherzig/pi-dvs/issues/19).
Market: Germany/EU, prices in EUR unless explicitly marked otherwise.

## Direction update — 21 October 2026

The preferred final appliance is now a **Pi directly behind a roughly 7-inch
touchscreen**, in a user-printed enclosure with two guest USB sockets. The user
already owns microSD storage, an Ethernet switch and Ethernet cables. See the
[compact Pi research and incremental budget](compact-pi-appliance.md) for used
boards, Chinese screens, enclosure planning and the plug-and-play software work.
That update supersedes the final-device purchase ranking below; the older complete
budgets remain comparison snapshots. The Omarchy Air remains useful for free
initial audio trials, rather than the intended final appliance.

[PiDeck implementation evidence](pideck-reference.md#hardware-inference) strengthens
the case for testing a Pi 4 Model B with 4 GB: it documents Pi 3 use and includes
explicit two-deck configurations. Pi 5 is headroom, not a proven minimum. The full
PX5/library/Link workload still needs measurement; no Pi performance pass is implied.

## Original recommendation and evidence status

**Test the owned 2015 11-inch MacBook Air, i7/8 GB, on its existing Omarchy
installation first.** Use its screen, keyboard and trackpad. The user confirmed
that this older Air runs Omarchy; it is not the Mac hosting the development
workspace. It is the best first candidate because a computer, display, input
devices and Linux installation are already available. This is a trial selection,
not a claim that its PX5 routing, latency, thermal behavior or appliance startup
have passed. The approximately 2012 HP i7/8 GB is the second reuse candidate,
especially if it has working Ethernet and an SSD.

Retain whichever owned laptop passes the full workload and reliability gates
below. Add a touchscreen only after the audio proof and a small-screen layout
trial. If reuse fails, the **ThinkPad X380 Yoga (€282.84 complete estimated
budget)** is the lowest-cost purchased touch candidate found; a **new Pi 5 setup
(€476.14)** is the compact modular alternative. The complete purchase
configurations below must pass the same gates. A more expensive
processor is not a solution to an unverified PX5 channel configuration or a
CDJ protocol limit. Do not purchase hardware based on this document alone.

Evidence labels used here:

- **Reported:** supplied by the user or recorded in an existing issue.
- **Verified source/code:** inspected documentation, seller page or repository;
  this does not mean tested on the device.
- **Estimate/proposal:** budget allowance, engineering assessment or acceptance
  target, not a measurement or a seller quote.
- **Unresolved:** requires inventory, an exact device/OS, a fresh offer or a trial.

No physical hardware runs were performed for this research. The comparison
cannot honestly name a configuration already proven to meet every requirement.
The decision is a prioritized validation path and conditional purchase shortlist.

## What the software actually needs

The baseline is `498e76086a95d068db259538922122170fe13a5b` on `main`.
Read [the dependency manifest](../pyproject.toml), [lockfile](../uv.lock),
[engine integration](xwax.md) and [current UI](../src/pi_dvs/ui/Main.qml):

- Python 3.12 is the selected development runtime; supported range is
  3.12–3.13. PySide6-Essentials is constrained to 6.10 and locked to 6.10.3.
  Pillow, SQLCipher3 and the Rekordbox parser must install too. Finding a Qt
  package for a board is not sufficient.
- The locked PySide wheels require glibc **2.34 on x86-64** and **2.39 on
  ARM64**, or macOS 13. There is no locked 32-bit ARM wheel. ARM64 Ubuntu
  24.04 is a concrete candidate; check the actual image's glibc rather than
  assuming any Raspberry Pi OS release works. Qt itself uses Pi 5 **with 8 GB**/Ubuntu
  24.04 as its desktop ARM reference; the 4 GB budget option needs its own trial.
  [Qt 6.10 platforms](https://doc.qt.io/qt-6.10/supported-platforms.html),
  [Ubuntu 24.04 libc6](https://packages.ubuntu.com/noble/libc6).
- Real audio uses a separately built, pinned and patched **Linux xwax 1.10**,
  ALSA, SDL2 and FFmpeg. The wheel contains no engine. The app and engine use
  local Unix sockets and the same local file paths. The current integration
  is not a remote control API, an iPad app or a native macOS audio engine.
- Library, artwork, decoding and network work compete for CPU/RAM/I/O, even
  though Python is outside the realtime audio callback. xwax retains decoded
  audio in memory; compressed file size is not a RAM estimate.
  [Upstream design](https://xwax.org/overview.html).
- The window defaults to 1120×980, with a **780×800 minimum**. The Air's
  1366×768 screen, a 720-pixel-wide portrait screen and many 800×480 panels
  require layout work. A 1280×800 panel only just meets the current minimum
  at 100% scale/fullscreen; it still needs a real usability check. A native
  high-resolution panel does not guarantee enough logical pixels at 200%.
- Status polling and the GUI timer run at about 100 ms. They are not the
  physical timecode-to-audio latency. Use physical audio measurements below.

The [#8 Link implementation](https://github.com/timherzig/pi-dvs/blob/055997fb8e4f9b29606e88b9c7d509cfca387025/docs/link.md)
is separate branch context, not present in this research branch's baseline.
It adds a Rust-built helper and a host-local cache (default 2 GiB).
Its recorded Mac/original-CDJ-900 tests do not prove Linux/PX5 support.
Retrieval is paced at 256 KiB/s: a 2.46 MB MP3 took approximately 11.2 seconds
in those earlier tests. A 100 MiB file has a **400-second transfer floor**
at that rate before overhead. More host CPU will not make that a two-second
load. Serving higher bitrate/high positive pitch remains
[#20](https://github.com/timherzig/pi-dvs/issues/20); do not treat that issue's
protocol investigation as a reason to buy a faster computer.

## Evaluate owned devices before buying

The inventory below incorporates the user's replies on the research date.
Do not substitute the development computer's specifications for these devices.

| Candidate | Known inventory | Missing inventory and first checks | Assessment |
| --- | --- | --- | --- |
| 11-inch MacBook Air, 2015 | User: Intel i7, 8 GB, **Omarchy/Arch Linux installed**. Apple's matching 11-inch Early 2015 family has an optional 2.2 GHz dual-core i7, 1366×768 display, Intel HD 6000, two USB 3 ports, Thunderbolt 2 and separate MagSafe 2 charging. | Confirm `MacBookAir7,1`, CPU SKU, SSD capacity/free space/health, Omarchy/kernel/glibc versions, graphics session, disk encryption/unlock, battery/45 W charger health and every port. Existing installation suggests basic Linux usability, not PX5 qualification. | **First full-host trial.** No initial OS replacement required. Built-in input is practical; screen-height layout work remains. Potential long-term appliance if health, recovery and thermal tests pass. |
| HP laptop, approximately 2012 | User: i7, 8 GB; likely x86-64, exact CPU/model unconfirmed. | Product/model code, exact CPU/GPU, current OS, SSD versus HDD/capacity, panel resolution, Ethernet speed, USB generation/controller layout, charger wattage, battery, fan and disk health. | **Second full-host trial.** If working Ethernet and SSD are present, it may need fewer adapters than the Air. A slow HDD, failing charger or thermal throttling can erase the reuse saving. Native Linux installation may be needed. |
| iPad Pro, 2017 | User: model year. The two applicable families are 10.5-inch and 12.9-inch second generation; both use 64-bit A10X and Lightning. | Settings → General → About: model number, size, capacity, installed iPadOS; RAM not recorded from the device; battery runtime, charger/cable, screen/touch condition and latest installable browser. | **Optional controller/display trial.** Full-host use is a substantial port, not an inexpensive deployment of today's stack. Keep audio and all music/cache processing on the separate host. |

Manufacturer evidence:
[Air specifications](https://support.apple.com/en-us/112441),
[Air identification and OS ceiling](https://support.apple.com/en-us/102869),
[10.5-inch iPad Pro](https://support.apple.com/en-us/111927),
[12.9-inch second generation](https://support.apple.com/en-us/111964).
The Air officially stops at Monterey, below this project's macOS minimum;
that matters only if reverting to macOS. Its existing Omarchy installation
avoids that particular obstacle. None of the specified iPad families qualifies
for [iPadOS 18](https://support.apple.com/en-ie/104986); check the installed
17.x build and available updates rather than guessing its current patch level.

### Initial reuse costs and later upgrades

These are **planning allowances**, not price-verified repairs or purchases.
The existing PX5, turntables, CDJs, music USBs and their working audio/mains leads
are sunk costs. Confirm what is already in the user's cable drawer before buying.

| Incremental item | Air | HP | Basis |
| --- | ---: | ---: | --- |
| Computer, built-in screen/input, existing OS | €0 | €0 | Owned; Linux software license cost €0, setup time excluded |
| Powered USB 3 hub, at least seven **data** ports, PSU included | €35–50 | €35–50 | Estimate; avoid counting charging-only outlets |
| USB 3 Ethernet adapter | €15–25 | €0 if working built-in Ethernet, otherwise €15–25 | Estimate; exact Linux chipset/driver must be checked |
| USB data leads for PX5/two controllers if missing | €0–15 | €0–15 | Estimate; reuse first |
| Dedicated five-port switch, PSU and three Ethernet patch leads if missing | €0 if owned; otherwise €30–45 | Same | Estimate; host + two players |
| **Immediate all-in reuse increment, no repairs** | **€50–135** | **€35–110** with built-in Ethernet; **€50–135** otherwise | Sum of rows; €0 possible if every accessory is already owned |

Storage and repair costs are conditional, not hidden inside those totals:
allow €25–45 for a conventional 240/256 GB SATA SSD for a compatible HP;
identify the Air's storage connector/adapter before quoting a replacement.
Allow €30–60 for a compatible replacement charger and €40–100 for a battery,
plus any labor. These are estimates, not repair offers; obtain exact parts
quotes after identification. A healthy battery buffers host power briefly,
but it does not power a disconnected hub, PX5 or switch. Do not count a failed
battery as a UPS or infer safe power-loss behavior from laptop branding.

A later external touchscreen adds the screen, stand, display adapter/cable,
touch USB and power supply listed in the purchase comparison. Those additions
are separate from the immediate reuse total. For the Air, HDMI panels need a
Mini DisplayPort/Thunderbolt-2-compatible video adapter; USB-C DisplayPort
adapters do not fit. Borrow a screen to test the layout before buying one.

### Omarchy trial and dedicated-appliance work

First inventory the **old Air itself**. These read-only diagnostics are for the
later hardware session, not commands already run against it:

```sh
cat /etc/os-release
uname -a
lscpu
free -h
lsblk -o NAME,MODEL,SIZE,FSTYPE,MOUNTPOINTS
getconf GNU_LIBC_VERSION
lsusb -t
lspci -nnk
ip -br link
aplay -l
arecord -l
```

Record battery/charger health and firmware identity locally without publishing
serial numbers. Inspect graphics, scale, lock screen, suspend/lid settings and
whether boot requires disk decryption. Run locked Python dependencies in a
project environment, not into Arch's system Python. Inventory the engine's
build dependencies from [xwax.md](xwax.md); adapt package names to the installed
Arch repository and SDL compatibility, then run the pinned native build/smoke.
The documented Ubuntu recipe has not been verified on this Omarchy installation.

Use the working desktop session for initial diagnostics. Later, #7 must supply
a dedicated session launching only the compositor, pi-dvs and required services;
disable routine desktop apps, screen locking, idle suspension and update jobs
during performance. Give xwax an independent service lifetime, bounded startup
waits, stable audio identity and realtime permissions. Resolve any encryption
unlock requirement as an explicit deployment choice; merely configuring
autologin does not remove an earlier disk-unlock prompt.

Omarchy's [update workflow](https://learn.omacom.io/2/the-omarchy-manual/68/updates)
updates application configuration and system packages. Record a recoverable
known-good image/package manifest and validate updates between sessions;
do not freeze an unsupported system indefinitely or partially upgrade Arch.
If that maintenance becomes burdensome, evaluate a supported LTS Linux
installation later. Reinstallation is not a prerequisite for the first trial.

### iPad local host versus remote controller

**Local host:** It is incorrect to say that PySide can never target iOS.
Qt documents new PySide iOS support starting in **6.12**, outside this project's
6.10 constraint. Its iOS deployment currently lacks supported third-party
package handling; native extensions need custom iOS builds. SQLCipher/Pillow,
QML resources, sandboxed music access, FFmpeg/import, xwax's ALSA backend,
multichannel capture/output, MIDI and Link serving would each need investigation.
An in-app CoreAudio engine would replace the Linux process/service assumptions.
This is a high-effort platform port even though the PX5 manufacturer documents
driverless iOS audio. [Qt announcement](https://www.qt.io/blog/python-mobile-app-development-bringing-pyside6-on-ios),
[deployment limitations](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-ios-deploy.html),
[PX5 drivers](https://www.allen-heath.com/hardware/xone-series/xonepx5/resources/).

Native development also needs compatible Xcode/signing hardware. Free personal
provisioning expires after seven days; paid distribution membership is
US$99/year or local pricing. That is a possible recurring port cost, not a
required subscription for a browser controller.
[Apple installation terms](https://developer.apple.com/help/account/basics/about-your-developer-account),
[membership](https://developer.apple.com/programs/enroll/).
Unattended launch after power-on, unlock and foreground/background behavior
remain unsolved requirements. Do not describe jailbreaking or a Linux container
as an established audio/driver solution.

**Remote display/controller:** First experiment with host-side screen sharing
of the existing QML application using a local VNC server plus
[noVNC](https://novnc.com/). It supports mobile browsers, but the actual
iPadOS 17 Safari build, graphics capture, text entry and gestures need testing.
This adds host setup and compression overhead; it is not a built-in pi-dvs
feature. A dedicated browser UI could improve touch behavior but requires a
host API and frontend implementation. Keep one host process owning the xwax
sockets; a second remote client must not steal its single-client connection.

- **Wi-Fi:** iPad on a private access point, host still wired to the CDJ switch.
  Use its existing Lightning charger. Extra hardware can be €0 if the AP,
  charger and stand are already owned; otherwise allow €25–50 for an AP,
  €10–20 for a stand and €15–30 for charger/cable. A wired CDJ network alone
  does not provide Wi-Fi. Test congested conditions; never route audio through
  the tablet. A host UI/engine must remain usable if Wi-Fi disappears.
- **Wired Ethernet:** Lightning-to-USB-3 Camera Adapter, compatible USB Ethernet
  adapter, patch lead and Lightning power input. Apple's adapter was **€49**
  on its German shop on the research date; allow €15–25 for Ethernet, €5 for
  the lead and €10–20 for a stand. Increment **€79–99**, or **€94–129** if a
  €15–30 charger/cable is needed, in addition to the host's complete setup.
  Verify the precise Ethernet adapter and simultaneous charging; Apple lists
  supported adapter examples. [Adapter price](https://www.apple.com/de/shop/product/mx5j3zm/a/lightning-auf-usb-3-kamera-adapter),
  [power/Ethernet support](https://support.apple.com/en-ie/111811).
- Lightning is not an HDMI video input. A generic USB cable is not automatically
  a Linux remote-display transport. Apple's
  [Sidecar](https://support.apple.com/en-us/102597) needs a compatible Mac
  (Air 2018 or later), so it does not solve this Air/Linux setup.
- Test taps, long lists, virtual keyboard, scaling/rotation, 30 disconnects,
  charging over a four-hour session and 10 wake/reopen cycles. All loaded audio
  must continue when the tablet sleeps, closes the browser or loses its cable.
  Reconnect must show fresh state, discard pending touches/commands and never
  replay an uncertain load. Retain the host screen or tested MIDI fallback.

For iPhones and other old iPads, apply the same exact-model/OS inventory and
deployment analysis. Smaller screens make two-deck browsing harder; newer
USB-C hardware can simplify cabling but does not port the engine.

For **Android**, Qt 6.10 already has
[PySide Android deployment](https://doc.qt.io/qtforpython-6.10/deployment/deployment-pyside6-android-deploy.html).
That makes UI reuse more plausible than an entirely new frontend. It still
requires Android wheels/native dependencies, storage permission handling and an
audio engine adapted to Android's audio/USB APIs, plus unattended startup and
power management. [USB host support](https://developer.android.com/develop/connectivity/usb/host)
is device-dependent. Require a concrete phone/tablet to demonstrate simultaneous
multichannel USB audio, Ethernet, media, MIDI and charging through its dock.
An unlockable Linux phone with working display/audio/USB drivers could change
the assessment, but no such device has been verified here. Borrowed Android
devices remain reasonable remote-controller candidates; do not buy one to avoid
the comparatively small cost of a native Linux host.

## Candidate category comparison

This is an engineering comparison using the sources in the inventory and BOMs,
not measured performance. “Full host candidate” means a plausible native
installation, subject to the complete validation gates.

| Category / concrete example | Full system or display only? | Practical benefit | Cost/maintenance reason to retain or defer |
| --- | --- | --- | --- |
| Owned 2015 Air, i7/8 GB, Omarchy | Full host candidate | Existing Linux, screen and input; separate charging | First trial. Inventory SSD/health; adapt 768-pixel layout and test shared USB/Ethernet. Rolling updates and AC-return behavior need appliance work. |
| Owned ~2012 HP, i7/8 GB | Full host candidate | May provide Ethernet and more ports without adapters | Second trial. Exact model, OS, disk and repair needs decide; age/i7 branding alone cannot rank it against the Air. |
| Owned 2017 iPad Pro | Controller first; full host needs port | Already-owned high-resolution touch panel | Remote setup adds a host, network and charging. Local port cost/installation restrictions outweigh the purchase saving for this project's first appliance. |
| New Pi 5 4 GB + touch | Full host candidate | Compact board, native Ethernet, reproducible component choices | Stronger new-SBC option than the almost equally priced new Pi 4; ARM64 package/graphics, cooling and microSD behavior need tests. |
| New/used Pi 4 4 GB + touch | Full host candidate | Mature board with the required external connections | New price saves little in the observed BOM. Borrow/reuse or evaluate a substantially cheaper used complete kit; inspect board/ports/PSU and include all missing accessories. |
| Other ARM SBC, e.g. ROCK 5C | Full host candidate with suitable image | Alternative I/O/performance choices | Official Debian 12 images do not satisfy this locked ARM wheel. A newer userspace, GPU support and ongoing kernel maintenance must be established before assigning it a cost advantage. |
| Integrated ARM screen, e.g. reTerminal CM4 | Full host candidate after adaptation | Screen, enclosure and eMMC integrated | 5-inch/720-pixel short edge and vendor display drivers add layout/OS work. No proven complete price/support advantage here. |
| Used thin client/mini/office PC, e.g. S740 | Full host candidate | Native x86 Linux, Ethernet and several ports; inexpensive base unit | Include SSD and external screen. Fanless S740 avoids a fan but still needs thermal testing; other office PCs trade larger footprint/fan noise for serviceable parts. Reject units with broken required ports. |
| Intel Surface Pro 6 | Full host candidate on Linux | High-resolution integrated touch, kickstand and charger | Community touch/kernel stack, battery repair risk and all peripheral traffic through one USB-A hub. Quoted offer needs freshness check. |
| ARM Surface RT / Pro X / SQ3 | Separate platform investigation | Integrated touch hardware | Not interchangeable with Intel Surface. The cited linux-surface support scope excludes these ARM models; boot, drivers and native engine deployment need a new proof before pricing them as equivalent hosts. |
| Used touchscreen convertible, e.g. X380 Yoga | Full host candidate | Integrated keyboard, screen, SSD and touch; fewer display cables | Price against the complete Pi/mini-PC bill. Exact panel, battery, USB ports and Linux touch/firmware matter; current offer below. |
| Old Android phone/tablet | Controller candidate; full host needs port | Reuse screen and mobile touch UI | PySide deployment exists, but engine/native dependencies, USB host/charging and unattended startup remain work. Test exact model; no blanket CPU-based exclusion. |
| Old iPhone/other iPad | Controller candidate; full host needs port | Existing device/browser can avoid a screen purchase | Exact OS/browser, small-screen usability and adapters matter. Signed native app plus engine port and lifecycle work is a different project from deploying the Linux stack. |

For all purchase options, first-year repair/maintenance risk is additional to the
working-unit BOM. Verify used battery capacity, charger authenticity/rating, SSD
health, screen/touch defects and every port within the return period. Obtain
exact-model battery/screen/charger quotes rather than assuming a generic
replacement fits. Reserve the €30–60 charger and €40–100 battery allowances from
the reuse section where appropriate; screen repair may make an integrated
tablet uneconomical and has not been quoted.

The purchase configurations need no paid OS or remote-display subscription for
the proposed Linux/local-screen path. Setup, diagnosis and ongoing maintenance
time are deliberately not converted to an invented hourly price: ordinary x86
Linux is the lowest integration burden; ARM board/display setup is additional
work; Surface's touch kernel adds an update dependency; Android/iOS full-host
ports are substantially greater work.

## Four complete purchase configurations


Prices were inspected on 20 October 2026; source crawl ages and stale offers are identified below. Prices include displayed VAT, with estimated delivery/parts separated. These are budgets, not checkout quotes. Shared accessories are itemized below; each total includes them once. Proposed OS: Ubuntu 24.04 ARM64 for Pi, Ubuntu 24.04 x86-64 for S740/X380, and Ubuntu 24.04 x86-64 plus the required linux-surface stack for Surface. No OS license purchase is budgeted.

| Candidate | Exact core configuration | Condition | Observed items subtotal | Estimated items and shipping | Total budget |
| --- | --- | --- | ---: | ---: | ---: |
| A: Pi 5 + Waveshare touch | BCM2712, four Cortex-A76 cores at 2.4 GHz; 4 GB RAM; proposed 128 GB microSD; 10.1-inch 1280×800 touch | New | €318.14 | €158.00 | **€476.14** |
| B: Fujitsu FUTRO S740 + same touch | Intel Celeron J4105, four cores, 1.5 GHz base; 4 GB RAM; listed 8 GB SSD replaced by proposed 128 GB SATA M.2 SSD | Used computer, new SSD/display/accessories | €298.68 | €153.00 | **€451.68** |
| C: Surface Pro 6 | Intel Core i5-8350U, four cores, 1.7 GHz base; 8 GB RAM; 128 GB SSD; integrated 12.3-inch 2736×1824 touch | Refurbished, seller grade Exzellent; new accessories | €355.82 | €118.00 | **€473.82** |
| D: ThinkPad X380 Yoga 20LJ | Intel Core i5-8350U, four cores, 1.7 GHz base; 8 GB RAM; 256 GB M.2 SSD; integrated 13.3-inch 1920×1080 touch and German keyboard | Used, Akzeptabel grade | €179.84 | €103.00 | **€282.84** |

These are conservative complete budgets, not quotes: estimates include two music USB
sticks, maintenance keyboard/touchpad, cables and a power strip that may already be
owned. Reuse can reduce A/B/C by up to the €138.84 shared bundle and D by €118.84 (its
keyboard is built in); only subtract items actually available. With the full respective
bundle already owned, the remaining budgets are A €337.30, B €312.84, C €334.98 and D
€164.00, retaining the delivery allowances. A higher-resolution external display or
additional RAM changes the budget. Four GB is a cost target requiring measurement under
the full two-deck workload, not an established minimum specification.

### Shared accessory baseline: €138.84 (€118.84 for D)

| Item | Observed or estimate | Cost |
| --- | --- | ---: |
| TP-Link UH700, seven-port powered USB 3 hub with PSU | Observed at [Reichelt](https://www.reichelt.de/de/de/shop/produkt/7-port-usb-3_0-hub_inkl_netzteil-149752), in stock, 1–2 working days; page crawled three days earlier | €39.85 |
| TP-Link LS1005G, five-port Gigabit switch with PSU | Observed at [Reichelt](https://www.reichelt.de/de/de/shop/produkt/switch_5-port_gigabit_ethernet-263637), in stock | €15.99 |
| Three Cat5e/Cat6 Ethernet patch leads: host to switch and two CDJs to switch | Budget, 3 × €3 | €9.00 |
| Three USB-A to USB-B data leads for PX5 and two RP-8000 MK1s | Budget, 3 × €5; reuse sound existing cables | €15.00 |
| Two 64 GB USB 3 music drives | Budget, 2 × €12; capacity must match the actual libraries | €24.00 |
| Wired keyboard with integrated touchpad, one USB connection | Budget for installation/recovery and text entry | €20.00 |
| Mains power strip | Budget for computer/display/hub/switch PSUs | €15.00 |
| **Total** | **Observed €55.84 + estimates €83.00** | **€138.84** |

The hub is a powered-port budget, not a claim that any particular hardware revision is
validated for multichannel isochronous audio. Confirm the supplied upstream USB cable
before ordering; [TP-Link's UH700
datasheet](https://static.tp-link.com/upload/product-overview/2025/202505/20250515/UH700%28UN%295.0_datasheet.pdf)
documents the product package. Boot-disk recovery media can reuse an available spare USB
device; the quoted two music drives are not substitutes for a separate backup of the
music library.

### Shared external display used by A and B

[Waveshare 10.1inch HDMI LCD (B), with case, model
WS-11769](https://www.tinytronics.nl/nl/displays/tft/waveshare-10.1-inch-ips-tft-lcd-display-1280*800-pixels-met-touchscreen-en-behuizing-raspberry-pi-compatible):
**€122.00** displayed by TinyTronics in the Netherlands, stock shown as 50+, dispatch
from Eindhoven. Retrieved October 20; source crawled the previous week. Includes
enclosure, mounting material, HDMI cable, micro-HDMI adapter and USB-A–micro-USB touch
lead. The seller's box list does not establish that the PSU and desktop stand are
included; allow **€15 for a suitable 5 V display PSU with power cable** and **€10 for a
stand/bracket**, and remove those allowances only after confirming the package. German
destination VAT/shipping can differ from the displayed Dutch total.

This is a compact, marginal-resolution budget display. Given the current app minimum of
780×800 and default window of 1120×980, 1280×800 requires a tested fullscreen/kiosk
layout at 100% scaling; the default window does not fit unchanged. Touch target sizing
and text input still require issue #5. A 1920×1080 or 1920×1200 screen offers more room;
no claim is made that a small high-DPI screen remains usable at arbitrary scale factors.

[Waveshare's own
manual](https://www.waveshare.com/wiki/10.1inch_HDMI_LCD_%28B%29_%28with_case%29)
distinguishes HDMI video, USB touch and a separate 5 V Power Only input. It lists
Raspberry Pi OS/Ubuntu/Kali support for Pi; its generic-Linux PC FAQ points to
`hid-multitouch`. This supports investigating Linux touch, not declaring the specific
x86/Ubuntu build verified. Test display detection, touch coordinates, screen rotation,
reconnect and fullscreen behavior on the exact revision.

### A. New Raspberry Pi 5, 4 GB

[Welectron Pi 5 4 GB](https://www.welectron.com/Raspberry-Pi-5-4-GB-RAM), **€118.00**
board, VAT included. The product page was crawled on the research date and showed 100+
stock at page level; select the board variant and recheck stock before purchase.
BCM2712/Cortex-A76 2.4 GHz, four USB-A ports (2 USB 3 + 2 USB 2), Gigabit Ethernet and
micro-HDMI. No storage/PSU/case is included in the board price.

| Item | Basis | Cost |
| --- | --- | ---: |
| Pi 5 4 GB board | Observed, Welectron above | €118.00 |
| Official 27 W USB-C EU PSU, attached power lead | Observed [Rasppishop](https://www.rasppishop.de/Raspberry-Pi-27W-USB-C-Netzteil-schwarz-EU) | €12.40 |
| Official Pi 5 case, fan and supplied heatsink | Observed [Rasppishop](https://www.rasppishop.de/Raspberry-Pi-Gehaeuse-inkl-Luefter-fuer-Pi-5-Schwarz-Grau) | €9.90 |
| 128 GB microSD for OS/app/cache | Estimate, exact endurance/performance model to select | €20.00 |
| Waveshare display and included HDMI/USB cables | Observed | €122.00 |
| Display power supply/cable and stand | Estimates €15 + €10 | €25.00 |
| Shared bundle | €55.84 observed + €83 estimated | €138.84 |
| Combined delivery allowance | Estimate, all sellers | €30.00 |
| **Total** | 118 + 12.40 + 9.90 + 20 + 122 + 25 + 138.84 + 30 | **€476.14** |

Use the fan supplied with this case; do not add a second cooler by assumption.
[Raspberry Pi recommends active cooling for sustained Pi 5 performance and commits to
production through at least January
2036](https://www.raspberrypi.com/products/raspberry-pi-5/). Long product availability
helps replacement planning, but RAM is fixed and microSD wear/power-loss recovery still
needs an appliance strategy. A better SSD boot arrangement is a separate upgrade with
enclosure/adapter/cable costs, not silently included.

USB plan: PX5 directly to host; one host port to powered hub; hub for two MIDI
turntables, two music drives, touch and maintenance keyboard = six downstream devices,
leaving one hub port. Use host Ethernet to the three-link CDJ switch. A direct USB
socket does not prove a separate host controller: inspect `lsusb -t` and test concurrent
music-drive reads/network transfers while audio runs.

**Pi 4 comparison:** the [Welectron Pi 4 Model B 4
GB](https://www.welectron.com/Raspberry-Pi-4-Modell-B-4-GB-RAM) page showed **€107.00**,
100+ page-level stock. BCM2711, four Cortex-A72 cores advertised at 1.8 GHz, 4 GB, the
same count of USB-A ports and Ethernet. Replacing the Pi 5 board/PSU/case (€140.30) with
the Pi 4 board (€107), an estimated 15 W USB-C PSU (€8) and suitable case/cooling (€15)
gives **€465.84**. Saving only **€10.30** is not compelling for a newly purchased Pi 4
when both need the same display and accessories. Reusing an already-owned Pi 4 could
change that decision substantially. This is not a performance benchmark.

### B. Used Fujitsu FUTRO S740

[eBay listing 389602245721, seller
itremarketingpl](https://www.ebay.de/itm/389602245721), **€57.00**, used, title
specifies J4105/4 GB/8 GB SSD/Wi-Fi/PSU and two-year warranty. Fresh source on October
20 showed eight available and listing updated October 19. Ships from Poland. Free
shipping was displayed for a non-German postcode, so German delivery remains a checkout
check and is covered by the allowance rather than assumed free.

[Fujitsu's manufacturer
datasheet](https://sp.ts.fujitsu.com/dmsp/Publications/public/ds-FUTRO-S740.pdf)
describes a fanless thin client. Its [earlier manufacturer datasheet, hosted by CNET
Content](https://cdn.cnetcontent.com/51/42/51428dad-e2db-486c-83f5-950612cf94c0.pdf),
specifies J4105, Intel UHD 600, one DDR4 SO-DIMM slot up to 8 GB, SATA M.2 storage and
Gigabit Ethernet. The six USB-A ports (two front USB 3, four rear USB 2) and DisplayPort
outputs are also documented by this [parts seller's S740
description](https://www.piosparts.de/Fujitsu-Futro-S740-ThinClient-Intel-J4105-1.50GHz-4GB-64GB-SSD-Incl.-Fuss-Netzteil/P38968).
Confirm the exact unit's ports and stand/PSU package.

| Item | Basis | Cost |
| --- | --- | ---: |
| Used S740 4 GB/8 GB, case, built-in passive cooling and PSU | Observed | €57.00 |
| Transcend TS128GMTS430S, 128 GB SATA M.2 2242 SSD | Observed [Proshop](https://www.proshop.de/SSD/Transcend-430S-SSD-128GB-M2-2242-42mm-SATA-600/2734547), order item, quoted 9–11 days; €4.99 delivery included within allowance below | €63.84 |
| Waveshare display/case/touch and included cables | Observed | €122.00 |
| Display PSU/cable and stand | Estimate | €25.00 |
| DisplayPort to HDMI adapter | Estimate; verify selected adapter's supported resolution | €15.00 |
| Shared bundle | As above | €138.84 |
| Combined delivery allowance | Estimate | €30.00 |
| **Total** | 57 + 63.84 + 122 + 25 + 15 + 138.84 + 30 | **€451.68** |

The 8 GB boot SSD is not the proposed deployment storage. Confirm the M.2 SATA socket,
2242 mounting point and SSD compatibility before ordering; do not substitute an NVMe
drive simply because its connector looks similar. RAM remains 4 GB in this priced
configuration; an 8 GB SO-DIMM is an additional cost if the load test requires it. Used
SSD wear, PSU condition, BIOS settings and AC-restoration behavior require inspection.
Generic x86 Ubuntu avoids a board-specific ARM userspace, but that is an installation
advantage, not an audio result.

USB plan: PX5 directly on the computer, music drives on available USB 3 paths where
possible, powered hub for remaining devices. Six native ports provide more wiring
choices than Pi/Surface, not six independent controllers. Host Ethernet connects to the
shared switch. Fanless cooling must survive the complete
sustained-load/ambient-temperature test.

### C. Refurbished Surface Pro 6

[Refurbed, seller
neXchance_IT](https://www.refurbed.de/p/microsoft-surface-pro-6-8350u/118181/):
**€296.99**, i5-8350U, 8 GB, 128 GB SSD, 2736×1824 touch, silver, Exzellent grade, PSU
included, keyboard absent, shipping included. Its displayed fee schedule adds **€2.99**
for this order value. **Freshness limitation:** retrieved October 20 but the source was
crawled the previous month and still displayed September delivery dates; the price is an
observed listing snapshot, not confirmed current availability. Obtain a fresh matching
offer before treating it as purchasable.

| Item | Basis | Cost |
| --- | --- | ---: |
| Surface Pro 6 with built-in screen/touch/case/cooling/stand, 128 GB SSD and charger | Observed snapshot | €296.99 |
| Platform service fee | Published €200–€300 order tier | €2.99 |
| USB 3 Gigabit Ethernet adapter | Estimate; select Linux-supported chipset and test the exact adapter | €20.00 |
| Shared bundle | As above | €138.84 |
| Accessory delivery allowance | Estimate; Surface listing already includes delivery | €15.00 |
| **Total** | 296.99 + 2.99 + 20 + 138.84 + 15 | **€473.82** |

One USB-A port means hub downstream usage is PX5 + two MIDI devices + two USB music
drives + Ethernet adapter + combined keyboard/touchpad = **seven ports**, all occupied.
The built-in touch screen consumes no external USB port. No separate audio connection is
available in this budget. Avoid assuming a powered hub eliminates controller contention.
Test all traffic together, plus charger noise, USB reconnection and battery/thermal
behavior.

[linux-surface's supported-device
matrix](https://github.com/linux-surface/linux-surface/wiki/Supported-Devices-and-Features)
requires its kernel for Surface Pro 6 touch. [Its installation
instructions](https://github.com/linux-surface/linux-surface/wiki/Installation-and-Setup)
add the community kernel and `iptsd`, with distribution-specific packages and possible
Secure Boot enrollment. This adds maintenance and rollback work compared with a
stock-kernel business PC. Preserve a known-good kernel/recovery path.
Battery/SSD/display repairs and exact replacement stock are risks for a used integrated
tablet. The matrix does not validate external PX5 audio.

### D. Lenovo ThinkPad X380 Yoga: complete €282.84 budget

[ITSCO X380 Yoga 20LJ, available “Akzeptabel / Gebraucht” variant
42678](https://www.itsco.de/2-in-1-touchscreen-notebook-lenovo-thinkpad-x380-yoga-intel-core-i5-8350u-4x-1-7ghz-20lj-42678.html)
displayed **€124 including VAT**, twelve available, 1–3 day delivery, retrieved October
20 from a page crawled the previous week. Exact offer: **i5-8350U, four cores at 1.7 GHz
base; 8 GB RAM; 256 GB M.2 SSD; 13.3-inch 1920×1080 IPS multitouch; original German
keyboard; PSU, mains cable and digitizer pen; no OS**. No specific functional defect was
disclosed in this variant's description. Its grade allows substantial cosmetic wear and
potentially missing nonessential covers; inspect the actual unit's screen, hinges and
ports. The **€179 “Gut” and €229 “Hervorragend” variants are sold out** when their
separate pages are opened; do not use those apparent selector prices as available
offers.

| Item | Basis | Cost |
| --- | --- | ---: |
| X380 Yoga, including screen, touch, keyboard/pointing devices, SSD, case, cooling and charger | Observed offer above | €124.00 |
| Shared accessories bundle, excluding redundant €20 keyboard/touchpad | Same hub, switch, three Ethernet leads, three USB leads, two music sticks and power strip as above | €118.84 |
| USB 3 Gigabit Ethernet adapter | Estimate; exact Linux-supported chipset to select/test | €20.00 |
| Delivery allowance for all remaining items | Estimate; [ITSCO's class-4 table](https://www.itsco.de/versand_und_lieferung) lists normal German delivery free over €99, so this allowance mainly covers accessories | €20.00 |
| **Total** | 124 + (138.84 − 20) + 20 + 20; **observed €179.84, estimates €103** | **€282.84** |

[Lenovo's
PSREF](https://psref.lenovo.com/syspool/Sys/PDF/ThinkPad/ThinkPad_X380_Yoga/ThinkPad_X380_Yoga_Spec.PDF)
confirms two USB-A 3.1 Gen 1 ports, one USB-C/Thunderbolt 3 port, HDMI, and native Intel
Ethernet through an optional proprietary extension cable rather than a normal RJ45
socket. It documents the 360-degree hinge, integrated keyboard/TrackPoint/touchpad and
soldered RAM with no upgrade socket. The offer only specifies M.2 SSD: SATA versus NVMe
and SSD brand are not established and need not be invented. The budget uses an ordinary
USB Ethernet adapter, avoiding an assumed-included proprietary cable.

**Port plan:** PX5 on one USB-A socket; powered hub on the other. Hub uses five
downstream ports for two MIDI turntables, two music drives and Ethernet. Built-in touch
and keyboard need no external USB ports. Two hub ports remain free. USB-C can accept the
supplied charger if it is that variant; the plan does not require a Thunderbolt dock. As
elsewhere, sockets do not establish independent USB controllers.

**Linux status:** [Lenovo's historical Linux certification
page](https://support.lenovo.com/sx/en/solutions/pd500182) covers an i5-8250U/8GB/256GB
X380 platform, and its [Linux platform
table](https://support.lenovo.com/de/de/solutions/PD031426) lists old RHEL/Ubuntu
support. These are useful evidence that Linux is a reasonable path; they do **not**
certify Ubuntu 24.04, this i5-8350U seller unit, current touchscreen behavior or PX5
operation. Begin evaluation with a maintained stock-kernel x86-64 distribution, verify
touch/pen/input and orientation explicitly, and prefer a fixed landscape kiosk
orientation until automatic rotation is proven. The FHD panel fits the current default
1120×980 window at 100% scaling; 125% scaling gives only 864 logical pixels vertically,
so test fullscreen sizing rather than assuming high-DPI scaling works.

**Specific maintenance gate:** [Lenovo's critical Thunderbolt
advisory](https://pcsupport.lenovo.com/us/en/products/laptops-and-netbooks/solutions/ht508988-critical-intel-thunderbolt-software-and-firmware-updates-thinkpad)
includes X380 Yoga and describes USB-C, charging, HDMI and controller failures. It
specifies X380 firmware R0STF18W / NVM 20 or newer in its table. Check actual firmware
and all affected ports before acceptance, and establish a supported update path; do not
assume installing Linux repairs an already-failed controller. Also inspect battery
health, BIOS/supervisor locks, SSD health and fan operation. No audio test has been
done.


### Other board/display evidence


- **Rockchip/Radxa SBCs:** capable ARM64 hardware is not automatically a smaller software burden. [ROCK 5C's official image list](https://docs.radxa.com/en/rock5/rock5c/download) includes Debian 12 images; those do not satisfy the locked `manylinux_2_39` wheel without a newer userspace or rebuilding dependencies. GPU/display/touch support, vendor kernel cadence, USB topology and thermal design need board-specific verification. No complete current EUR BOM with those gates resolved was established, so it is not promoted above Pi or x86.
- **Integrated CM4 reTerminal:** [Seeed's documentation](https://wiki.seeedstudio.com/reTerminal/) specifies 4 GB RAM, 32 GB eMMC, a 5-inch 1280×720 screen, two USB 2 ports and Gigabit Ethernet, with vendor OS/driver procedures. Its 720-pixel short edge cannot meet the current app's 780×800 minimum in either orientation, and a 32-bit/Bookworm image does not meet the ARM64 wheel requirement. Integrated packaging does not make it a drop-in deployment.
- **Official Pi touch displays:** [Touch Display 2](https://www.raspberrypi.com/products/touch-display-2/) has 720×1280 5-/7-inch variants: their short edge is also below the current minimum. The newer 10-inch 1200×1920 variant has more suitable resolution, but [compatibility differs](https://www.raspberrypi.com/documentation/accessories/touch-display-2.html) and no exact complete German-priced case/stand/board bundle was confirmed here. A DSI touch display can free a USB connection; it still needs kiosk and touch validation.
- **Surface RT/ARM variants:** do not substitute them for the Intel Surface Pro 6 BOM. The linux-surface device matrix explicitly excludes ARM Surface RT/Pro X/SQ3 models from its normal support scope.


### What extra spending buys

After reuse, **D is the lowest complete purchase budget found**, conditional on
unit health and the validation gates. It combines the screen, keyboard and SSD
and leaves the PX5 a direct USB port. Choose it over a new Pi setup only if the
13.3-inch footprint, used condition and firmware maintenance are acceptable.

A is the worthwhile alternative when a small separately mounted appliance and
new replaceable components matter: **€193.30 more** than D buys a new board,
power/cooling package and separate display, plus the Pi ecosystem's documented
platform path. It does not buy a demonstrated latency improvement. A new Pi 4
saves only €10.30 in this comparison. Do not buy more RAM or NVMe before measuring
actual memory pressure and decode/I/O bottlenecks. B is fanless and serviceable
but its SSD upgrade/display costs erase much of the cheap base-unit advantage.
C buys a compact high-resolution integrated tablet, with more touch-driver and
USB-topology maintenance; it is not the budget winner.

Air/X380/Surface combine screen, input and host power into fewer boxes; Pi/S740
require separate display, mounting and power leads. The S740 is fanless, Pi 5's
case includes a fan, and the laptops' fan behavior is unmeasured. None has a
verified power-consumption or noise advantage in this workload. The trial records
wall power, fan noise, dimensions/cable placement and screen visibility at the
actual working distance. Battery buffering, automatic AC recovery and clean
shutdown must be tested separately for every candidate.



## Simultaneous connection plan

The [PX5 datasheet](https://www.allen-heath.com/content/uploads/2023/06/PX5-Technical-Datasheet.pdf)
specifies a USB 2, 10-input/10-output interface. Its
[user guide](https://www.allen-heath.com/content/uploads/2023/06/AP10733_2_XONE_PX5_USER_GUIDE.pdf)
describes phono/line send routing and selectable sample rates.
Class compliance is a feasibility signal; Linux duplex channel mapping and
two-deck operation remain #4 tests. Budget no separate soundcard/HAT.

```text
Turntable A/B analogue outputs -> PX5 phono inputs -> host via ONE USB audio cable
Host xwax stereo outputs A/B  -> PX5 USB return channels -> mixer/master

Host Ethernet ------ dedicated switch ------ original CDJ-900 #1
                                  \-------- original CDJ-900 #2
Host USB hub ------- local music USB #1 and #2
             \------ RP-8000 MK1 A and B USB/MIDI
             \------ touchscreen USB (where applicable)
Host video --------- external screen (or built-in screen / Pi DSI)
Independent power -- host + hub + display + switch + PX5 + turntables/CDJs
```

Prefer the PX5 on a native host USB port. Put controllers, touch and two music
drives on a powered hub. The Air's second USB port must accommodate that hub
and Ethernet: **six data sockets** for two controllers, two music drives,
Ethernet and optional USB touch. A seven-data-port hub leaves one spare.
MagSafe charging is independent. If a Thunderbolt Ethernet adapter is already
owned, test it as an alternative; do not buy one before testing cheaper USB.

Reloop's [MK1 documentation](https://www.reloop.com/reloop-rp-8000) describes
Turntable Link chaining up to four decks to one host USB connection. That could
save a hub port, but use two direct hub connections for the initial budget.
#11 must verify Linux MIDI enumeration, persistent A/B assignments, the TRAX
encoder and reconnection before relying on chaining. MIDI control belongs to
the app; the current headless xwax socket mode disallows native MIDI controllers.

For Pi/mini-PC options, use native Ethernet; Pi DSI touch avoids video/touch USB
cables. A Surface's single USB-A requires a hub for the PX5 too; test this
shared-uplink layout explicitly. Separate sockets are not proof of separate
host controllers: retain `lsusb -t`, `lspci` and kernel logs for every layout.
Exercise USB copies, both players and both decks concurrently. A powered hub
solves port/power capacity, not scheduling contention. Do not add an SSD, audio,
Ethernet and display to one bus and infer suitability from advertised Gb/s.

Use stable device identities rather than card numbers. Verify the actual ALSA
format and both stereo capture/playback pairs, including an explicit shared
10-channel device strategy; two independent stereo opens may conflict.
Start by inspecting direct ALSA access and any PipeWire ownership on Omarchy.
Avoid accidentally sending timecode through desktop effects/resampling or
letting another process seize the PX5. Select conversion/routing only after
observing supported formats, then measure its latency.

## Proposed minimum and acceptance targets

These are **pre-trial engineering targets**, not benchmark results or permanent
minimum specifications. They make a purchase conditional on measured behavior.

| Resource | Trial floor and rationale |
| --- | --- |
| Platform | Native 64-bit Linux, x86-64 or ARM64, compatible locked packages and working accelerated Qt Quick/touch stack. No virtual machine in the audio qualification path. |
| CPU | Start with owned i7/8 GB or shortlisted four-core low-power systems. No GHz-only minimum: timecode, imports, UI and Link concurrency decide. |
| RAM | 4 GB candidate minimum; 8 GB preferred when already owned or inexpensive. Require at least 1 GiB available under the prescribed workload and no sustained swap-in/out while playing. Long mixes need a separate duration limit. |
| Storage | At least 32 GB usable OS storage and 8 GiB free after installation/cache; 64 GB or larger preferred, SSD for x86. Include logs/artwork and bounded audio cache, not just program size. OS/cache separate from read-only music USBs. |
| Connectivity | Stable full-duplex PX5 plus Ethernet, two media USBs, two controllers and display/touch simultaneously, with power margin. 100 Mb/s Ethernet is sufficient for the currently paced Link data rates; Gigabit is a useful common feature, not proof of compatibility. |
| Display/input | Built-in screen/keyboard for first proof; practical final touch target 10–12 inches, readable at working distance, stable stand, usable angle/glare, correct physical touch size and touch-only text entry. Smaller Pi panels require a deliberately adapted layout. |
| Thermal/power | Correct continuous-rated supplies, no undervoltage or thermal throttle during the full run, safe shutdown, tested recovery and retained diagnostic logs. |

For scale, two 10-minute tracks decoded as 44.1 kHz stereo 16-bit PCM have a
raw payload of `2 × 600 × 44100 × 2 × 2 = 211,680,000` bytes (about 202 MiB).
That is a **lower-bound planning calculation**, not xwax's total allocation:
indexes, over-allocation, old/new tracks during loading, UI, artwork, OS and
helpers also consume RAM. Two hour-long mixes multiply that payload by six.
The test must report actual peak memory for the longest intended files.

| Measurement | Proposed gate | Why / method |
| --- | --- | --- |
| Cold power-on to usable UI | 10 cold starts: median ≤30 s, worst ≤45 s | Reasonable first appliance budget including firmware. Start timer at power button/AC return, stop when search/input works; record unlock/login interactions as failures of unattended mode. |
| Power-on to playable deck | Median ≤40 s, worst ≤60 s with a specified local 5-minute track and devices already powered | Separate audio enumeration and load time. Include human selection timing separately or use a fixed scripted load; never start unexpected playback to satisfy timing. No 10–15 s promise. |
| Tap/key feedback | At least 100 actions: p95 ≤100 ms, worst ≤250 ms | Video at ≥120 fps or timestamped input-to-frame instrumentation. Measure highlighting/acknowledgement separately from 100 ms engine telemetry. |
| Search/playlist navigation | 10,000-track export, 100 queries/transitions: p95 ≤200 ms, worst ≤500 ms after catalog import | Include accents, long names, empty results and artwork. Repeat at 50,000 tracks to characterize growth; report a capacity limit if it fails. |
| Scrolling | Sustained ≥30 visible fps; no pause >100 ms during a 60-second scroll | Trace frame times and record dropped frames during simultaneous import/transfer. Remote iPad adds its own network/display delay. |
| Local/cached load | 30 unique 5-minute MP3 and PCM files per class: median ≤2 s, p95 ≤3 s, worst ≤5 s from accepted selection to confirmed READY | Measure storage/cache verification and full decode, not only the initial button response. Separate cold filesystem cache, warm OS cache, and already-decoded xwax cache. |
| Network load | Record transfer, verification, decode and UI phases separately; no fixed local-load SLA | Baseline byte size / 256 KiB/s plus measured protocol/queue overhead. Flag a regression against the same file/revision/topology; uncached download time is not host decode speed. |
| DVS response | Physical input-event-to-output p95 ≤10 ms, worst ≤15 ms, with no audible stalls | Proposed scratching target to confirm with the DJ. Start with 128/256-frame periods at a supported rate; record actual negotiated periods/buffer. Do not equate one period's duration to round-trip latency. |
| Dropouts/headroom | Zero audible glitches and zero new capture/playback XRUNs in a 4-hour loaded run | Sample per-core CPU/RSS/I/O/temperature every second. Target busiest-core p95 <75%, no >90% plateau for 10 s, ≥1 GiB available RAM and no ongoing swap. Bursts alone do not fail if audio remains correct. |
| Thermal stability | No throttle/undervoltage flags; last-hour p95 UI/load time within 20% of first-hour results | Log ambient conditions and display brightness; repeat at the warmest intended venue condition before declaring field readiness. |
| Recovery | 10 cycles per hardware failure; 30 for a remote tablet | Loaded host audio survives UI/controller/tablet loss. Reconnect UI/control within 5 s of device/session availability; source discovery ≤10 s after OS mount/network return, with import time reported separately. No duplicated loads or deck swaps. |

If targets fail, preserve results and distinguish a layout/software bottleneck,
driver/topology problem and insufficient hardware. Tune one variable at a time;
do not revise thresholds after the run solely to declare a pass.

## Reproducible trial on the actual rig

1. **Inventory and freeze the comparison.** Start with the owned Air, then HP;
   borrow competing devices if reuse fails. Record exact model/CPU/RAM/storage,
   firmware, battery/charger state, OS image, kernel, glibc, Mesa/Qt renderer,
   scale/resolution, governor, power policy, USB tree, ambient temperature and
   all powered accessories. Record app commit, `uv.lock` hash, xwax source/patch
   hashes, helper revision and service configuration. Use one set of media and
   cables for comparisons.
2. **Installability and UI screen-fit.** On the target, install locked
   dependencies and run `make check`; build the pinned native xwax smoke.
   Offscreen tests do not prove accelerated graphics. Launch real QML, exercise
   the 768-pixel Air screen and real-mode UI, then record layout fixes needed
   for #5. Never label the silent demo as an audio pass. Test an installed
   wheel with `make package` when qualifying the deployment recipe.
3. **Prove PX5 mapping before optimization.** Record mixer firmware, USB
   capture/playback descriptors, format/rate/periods, realtime priority and
   locked-memory limits. Test each channel's left/right separately, then two
   decks together through the same PX5. Record rear PH/LN sends and front
   source switches. Test both user vinyl sides, forward/reverse, stops, cue
   positions and scratching; coordinate absolute/runout behavior with #12.
4. **Create representative media.** Use the user's actual export (report only
   aggregate statistics), plus a lawful reproducible 10,000-track metadata/
   artwork stress library. Retain a manifest of sizes, formats, duration and
   hashes. Test 5-minute MP3 and 44.1 kHz/16-bit PCM, Unicode paths, missing
   artwork, long tracks and corrupt files. Use the same 100 queries and playlist
   sequence. Measure catalog import time separately; repeat after cache reset
   only while idle and preserve loaded/queued cache pins.
5. **Measure latency and load in isolation, then under stress.** Capture a
   synchronized reference of the control signal/event and analogue mixer output
   with an independent multichannel recorder/interface or oscilloscope, borrowed
   if necessary. Keep levels safe and use a known audio transient/marker to
   measure starts/stops/reversals; record calibration delay, at least 100 events
   per condition and p50/p95/max. Compare GUI absent, idle, browsing, decoding and
   transfer cases. Without this equipment report latency **unmeasured**.
6. **Exercise both Link directions on the integrated revision.** Merge/use the
   accepted #8 implementation in the future trial checkout first. Two original
   CDJ-900s on firmware 4.32 are the previously reported baseline; record the
   actual firmware. Test a USB in each CDJ in turn → host cache → real DVS,
   then host USB → both CDJs. Keep two real DVS decks playing throughout;
   perform fresh paced downloads, cached loads, artwork and local USB scans.
   Add two local and two remote sources for #18, preserving source identity.
   Match hashes; listen to both CDJs and both PX5 decks. High bitrate/WIDE
   results belong in #20 as well as the hardware record.
7. **Run for four hours.** Alternate ten-minute idle/playback and browsing/
   scrolling/loading/network phases, with both decks active except intentional
   protected load changes. Compare first/last-hour metrics. Include one
   60-minute track per deck to expose decoded-memory pressure. Repeat a
   shorter two-hour cross-check on the other owned laptop if practical.
8. **Recovery and appliance behavior.** In a controlled session, separately
   restart/close the UI, interrupt the helper/Ethernet, remove/reinsert USB
   media, disconnect/reconnect each controller, and sleep/disconnect the iPad.
   Verify already-cached host audio separately from local-source playback;
   do not promise a CDJ's stream survives removing its source USB. PX5 loss
   necessarily loses that audio path: require an honest error, bounded recovery
   and no unsolicited playback after reconnect. Engine restart must not silently
   reload/start decks.
9. **Cold boot and power interruption.** Only after #7 setup exists, perform ten
   cold starts and ten controlled power-return tests on backed-up test storage.
   Check firmware auto-on behavior explicitly: a laptop requiring its power
   button after AC returns is not yet an unattended-recovery pass. Verify the
   intentional shutdown action, read-only user media, cache/settings integrity,
   full-disk behavior, boot with devices absent and reconnect after arrival.
   Monitor wall power with a meter at idle and peak load; record fan noise at
   working distance and actual cable footprint. Do not quote PSU wattage as
   measured consumption.

Collect `pidstat`, `vmstat`, temperature/frequency and kernel/service logs using
the target's available tools, with timestamps and sampling intervals. Avoid
printing inside realtime callbacks. xwax provides `DVS2 METRICS` counters:
collect before/after as [documented](xwax.md#verification-and-hardware-measurements)
with the GUI disconnected, because a new client replaces its connection.
For live logging, add telemetry through the existing connection in a separately
scoped change; do not poll the sockets from a second monitoring process.
Zero XRUNs alone cannot establish correct or inaudible audio.

Use this record for each candidate; all values are **not measured** today:

| Record | Required contents |
| --- | --- |
| Identity and reproducibility | Date/operator, exact BOM and condition, all versions/hashes, OS/service configuration, USB/network diagram, media manifest |
| Boot (10) | Each UI/playable time, median/worst, missing-device cases, any human unlock/login |
| UI and loads | Sample counts; p50/p95/max; cold/warm/decoded cache split; file sizes/formats; library cardinality; video/trace paths |
| Audio | Actual sample rate/format/periods/channel map, measurement apparatus/calibration, p50/p95/max response, listening notes and before/after XRUN counters |
| Sustained/recovery | Duration, CPU per core/RAM/swap/I/O, temperature/throttle, wall watts/noise, failures and reconnect times |
| Decision | Pass/fail/not measured for each gate, unresolved failures, exact software/hardware change needed, complete incremental cost |

## Consequences for the other tickets

| Ticket | Change in planning |
| --- | --- |
| [#4 PX5 proof](https://github.com/timherzig/pi-dvs/issues/4) | Make the first proof on the owned Linux Air; preserve two-deck/routing/vinyl criteria. A Pi becomes a comparative target if its footprint or cost justifies it. |
| [#5 touchscreen](https://github.com/timherzig/pi-dvs/issues/5) | Fix the 768-pixel-height laptop case first, retain keyboard operation, then test borrowed 10–12-inch touch. A 7-inch portrait panel needs a specific layout, not only rotation. Keep virtual keyboard and scaling in scope. Remote tablet UI is a distinct deployment option. |
| [#7 startup/recovery](https://github.com/timherzig/pi-dvs/issues/7) | Start from the selected Linux host; independent engine/UI services, no routine desktop/login, handle encryption and firmware AC-return behavior, bounded missing hardware, safe shutdown and reproducible updates. Omarchy desktop autostart alone is insufficient. |
| [#6 USB lifecycle](https://github.com/timherzig/pi-dvs/issues/6), [#18 sources](https://github.com/timherzig/pi-dvs/issues/18) | Budget two local music ports and mixed local/remote sources. Validate mount identity, source-only failure and unchanged media. |
| [#8 Link](https://github.com/timherzig/pi-dvs/issues/8), [#20 expanded rates](https://github.com/timherzig/pi-dvs/issues/20) | Preserve actual original-CDJ compatibility limits and complete-download timing; repeat with real Linux/PX5 concurrency. Faster hardware does not close unresolved protocol tests. |
| [#11 RP-8000](https://github.com/timherzig/pi-dvs/issues/11) | Test the two MK1s on the chosen host, including deck identity and reconnect; validate USB chaining before removing hub capacity from the BOM. |

This document proposes those planning changes; it does not edit or close the
issues. Physical trials, purchases, platform ports, appliance services and UI
implementation remain follow-up work. Remaining inventory is the Air's SSD/
health/Omarchy versions, exact HP identity and condition, iPad size/OS/condition,
existing adapters/switch/cables and desired longest track/library size.
