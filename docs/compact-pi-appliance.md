# Compact Pi appliance with guest USB ports

Research update: **21 October 2026**, for [#19](https://github.com/timherzig/pi-dvs/issues/19).
This is the preferred final form factor; the broader [hardware comparison](hardware.md)
remains useful for validation and alternative test hosts. No target hardware has been tested.

## Direction and owned parts

The user wants a Raspberry Pi directly behind an approximately 7-inch touchscreen,
in a self-printed enclosure near the top of the Xone:PX5. Two accessible USB sockets
should let guests insert Rekordbox exports, browse playlists and load either deck.
Used boards and Chinese displays are welcome. The user already owns a printer,
microSD card, Ethernet switch and Ethernet cables. Exclude those from new spending.
A Pi, suitable PSU, cooling and powered USB hub have not been reported as owned.
The old Omarchy MacBook Air is a free audio-development test host, not the final enclosure.

**Preferred screen: official 7-inch Touch Display 2, SC1635, in landscape.**
Its DSI connection carries video and touch without consuming a USB port. The Pi can
mount directly on its back. Power comes from the Pi GPIO header; the kit includes
the Pi 4 and Pi 5 display cables. Landscape gives 1280×720; the panel is approximately
189.5×120 mm. [Official integration documentation](https://www.raspberrypi.com/documentation/accessories/touch-display-2.html).
The observed German price is **€59.90 including VAT**, orderable with an advertised
approximately three-week lead time, excluding shipping.
[Welectron exact 7-inch listing](https://www.welectron.com/Offizielles-Raspberry-Pi-Touch-Display-2).

Prefer a used Pi 4 4 GB only at a meaningful saving after PSU and cooling are counted.
The [PiDeck precedent](pideck-reference.md) makes Pi 4 4 GB a credible budget
implementation target; choose Pi 5 for extra headroom when the complete-price gap
is small. Neither RAM size nor processor
has been qualified for two-deck PX5 playback plus library imports and Link traffic.
Do not pay for 8 GB simply because the listing includes it; measure peak memory first.

## Display shortlist

Prices are observed product-page prices, not reserved offers or Germany checkout totals.
USD quotes exclude unverified delivery, VAT and currency conversion.

| Exact display | Interface / native pixels | Observed price | Assessment |
| --- | --- | --- | --- |
| [Official Touch Display 2 7-inch SC1635](https://www.welectron.com/Offizielles-Raspberry-Pi-Touch-Display-2) | DSI, 720×1280; rotate | €59.90 incl. VAT | Preferred integration and USB availability; confirm delivery |
| [Waveshare 7inch HDMI LCD (H), SKU 14628](https://www.waveshare.com/product/7inch-hdmi-lcd-h.htm) | HDMI + USB touch, IPS 1024×600, capacitive | US$47.99 | Viable alternative; USB touch and HDMI cable need enclosure space |

The Waveshare manufacturer lists an HDMI cable, micro-HDMI adapter, USB touch cable
and screws. Verify the exact revision and power input arrangement before purchase.
The H, C and other similarly named models have different boards and dimensions;
their CAD and instructions must not be interchanged.

For used screens, ask for the exact rear-board model and a powered image with touch
demonstrated across the entire panel. Check glass, DSI connector latch, cable, power
lead and screw hardware. A used original official 7-inch **800×480** display is not
Touch Display 2 and needs a different enclosure and more constrained UI. An asking
price around €25–35 for a complete working older panel is a proposed negotiation
target, not a verified available offer. At close to €60, prefer the new TD2.

For AliExpress, compare the selected **7-inch capacitive touch** variant, shipped to
Germany, against the €59.90 local screen. Listing headline prices may select a
non-touch panel, accessory or smaller size. Require an exact controller/model,
Linux instructions, dimension drawing, included cables and the complete tax/shipping
total. No AliExpress checkout price was verified in this research. A genuinely
€30–40 delivered HDMI/USB panel could be attractive; that is a buying threshold,
not a current quotation. Avoid SPI/resistive panels for this library UI.

## Incremental budget

The priced board offers and additional manufacturer screens appear below. A new
Pi 5 reference uses €118 board + €12.40 official 27 W PSU + €5.90 active cooler +
€59.90 TD2 = **€196.20**, before shipping and the following allowances.
This is a price reference, not a confirmed immediately available basket: the Pi 5
retailer stock/variant needs reconfirming and the display advertises a lead time.

| Remaining item | Planning allowance, not a quotation |
| --- | --- |
| Two short USB 3 panel-mount male-to-female extensions | €10–20 total |
| Printed shell, inserts, screws and mounting hardware | €5–15 |
| Powered four-port USB hub including its PSU, for both RP-8000s | €20–35 |

Thus allow **€231.20–266.20 plus shipping** for the new-Pi reference, reusing the
owned storage and networking. Without the turntable hub, the first PX5/local-USB
prototype is **€211.20–231.20 plus shipping**. Add any missing PX5/RP USB cables
after inventory; these totals assume the rig's existing device cables are available.
Do not buy a commercial Pi case, keyboard, SSD, separate stand, switch or Ethernet
adapter by default. The enclosure replaces the case, not the cooler or PSU.

## Connections and enclosure

Proposed layout, subject to actual concurrent USB/audio testing:

```text
7-inch DSI display + GPIO power
          │
Pi behind display
├── USB 3 → front guest USB A socket
├── USB 3 → front guest USB B socket
├── USB 2 → Xone:PX5 directly
├── USB 2 → powered hub → RP-8000 MK1 × 2
└── Ethernet → owned switch → original CDJ-900s
```

An HDMI display adds its USB touch connection to the hub. Ports are not independent
controllers: this arrangement does not prove bandwidth or dropout isolation.
Use the correct board PSU and test total screen/guest-device power demand. A powered
hub adds power and sockets, not a dedicated audio bus.

Put the two panel sockets below or beside the glass, with replaceable short extension
leads and strain relief so insertion force reaches the printed shell. Leave space
between sticks, cable bend clearance, cooler airflow and microSD service access.
A rough TD2 enclosure envelope of **210×150×40–55 mm** is a concept allowance only.
Measure the selected display, cooler and connectors before CAD; no STL is validated.
Prototype an adjustable rear/desk bracket in cardboard before printing. Keep mixer
controls, vents and rear cables accessible; the exact mixer attachment remains open.

## What “plug and play” requires in software

The [PiDeck implementation reference](pideck-reference.md) maps relevant audio,
automount, small-screen and startup code to our tickets, with specific adaptation
boundaries.

The desired sequence is: boot directly into pi-dvs → insert stick → source appears
with progress → choose playlist/search → load deck → show safe-eject status.
The hardware enables this, but the current app does not yet guarantee this workflow.

- Adapt [Main.qml](../src/pi_dvs/ui/Main.qml), currently minimum 780×800, to
  1280×720 and 1024×600. Use a large browser/search view with persistent deck status;
  make detailed deck information a separate view. Test finger targets, touch rotation,
  onscreen keyboard and keyboard dismissal. Do not shrink the desktop UI to fit.
- [#6](https://github.com/timherzig/pi-dvs/issues/6) and
  [#18](https://github.com/timherzig/pi-dvs/issues/18): automatic source discovery,
  read-only mounts, two distinct guest sources and stable identity after reconnect.
  Show unsupported filesystem/export format, unreadable files and import progress.
  Traditional `export.pdb` and OneLibrary `exportLibrary.db` need separate real fixtures.
- Import/index off the audio path. Never silently replace a playing deck; handle a
  second stick or damaged export without interrupting the first guest's playback.
  Safe eject must account for open/playing files and pending reads. Only a completely
  cached file can be considered independent of its source; do not promise arbitrary
  unplugging while loading or streaming.
- [#7](https://github.com/timherzig/pi-dvs/issues/7): supervised engine/app startup,
  recovery, clear ready/error status and an accessible shutdown action. No login
  dialog or terminal should be needed for ordinary use.
- Preserve the full [real-rig validation gates](hardware.md): two-deck DVS through
  PX5, simultaneous guest imports, MIDI and wired Link, thermal soak and recovery.
  Buying a Pi does not resolve the existing original-CDJ-900 transfer/protocol limits.

Try **64-bit Raspberry Pi OS based on Debian 13 Trixie** for the official display.
The [official OS catalog](https://www.raspberrypi.com/software/operating-systems/)
identifies this base; [Trixie libc6](https://packages.debian.org/trixie/libc6) is 2.41,
above the locked ARM64 PySide wheel's 2.39 minimum. This is a dependency-compatible
candidate, not an install result: validate locked Python dependencies, SQLCipher,
Qt graphics/touch and the pinned xwax build on the actual image. No 32-bit OS.

## Used-board and additional Chinese-display evidence

## Exact used listings

All are private Kleinanzeigen offers. “VB” is the advertised negotiable asking price; no negotiation or discount is assumed. “Shipping from” is the page's minimum, not a confirmed insured parcel quote. Listed condition and successful operation are seller claims.

| Exact offer | Observed asking price and condition | Included / missing | Useful comparison |
| --- | --- | --- | --- |
| [Pi 4 Model B 4 GB, Pliezhausen](https://www.kleinanzeigen.de/s-anzeige/raspberry-pi-4-model-b-4gb-64gb-sd-luefter-netzteil-mini-pc/3468963978-228-7988), ad 2026-07-26 | **€85**, “Sehr Gut”; shipping from **€6.19** | 4 GB board; 64 GB SanDisk Extreme Pro A2 microSD; loose 5 V/GND fan; **non-original PSU, model/rating not given**. No case specified. | Minimum shown €91.19 delivered; add an **estimated €8** official Pi 4 PSU if its supplied PSU cannot be verified: **€99.19 host reference**. Fan mounting still requires enclosure work. The extra SD is already redundant. Older indexed listing, availability uncertain. |
| [Pi 4 8 GB, Buttenheim](https://www.kleinanzeigen.de/s-anzeige/raspberry-pi-4-8gb-ram-wie-neu-usb-rs485-wandler-kabel/3544073934-228-6286), ad **2026-10-18** | **€105 VB**, “Sehr Gut”; shipping from **€1.99** | 8 GB board/box; **USB-C cable, not a mains PSU**; RS485 adapter and two DisplayPort dummy plugs. No storage/cooling stated. | €106.99 minimum; add **estimated €8 PSU + €10 cooling** = **€124.99 host reference**. This is close to new Pi 5 core cost and spends money on RAM rather than CPU headroom. Freshly indexed on the research date. |
| [Pi 5 4 GB in Argon NEO 5, Gilching](https://www.kleinanzeigen.de/s-anzeige/raspberry-pi-5-4gb-ram-im-argon-neo-5-gehaeuse-netzteil/3536939193-228-15740), ad 2026-10-10 | **€130 VB**; seller describes it as maintained and working; shipping from **€6.19** | 4 GB Pi 5; Argon aluminium case with fan; “USB-C-Ladekabel/Netzteil” **without rating/model**. No storage stated. | **€136.19** minimum with supplied power. If a suitable 5.1 V/5 A supply cannot be established, add official €12.40 = **€148.59**. Case/cooling arrangement must be reconsidered when the Pi goes behind the screen. |
| [Pi 4 4 GB + 7-inch touch bundle, Wolfsburg](https://www.kleinanzeigen.de/s-anzeige/raspberry-pi-4-b-4gb-ram-7-touch-display/3472198476-228-3075), ad 2026-07-30 | **€130 VB**, “Sehr Gut”; shipping from **€2.99** | 4 GB Pi 4; 7-inch touch screen and case; CPU cooler/Noctua fan; matching Pi PSU. No SD stated. **Screen model, resolution, IPS status, touch technology and DSI/HDMI interface all unspecified.** | **€132.99 minimum for host + display**, potentially useful only after model/PSU identification and availability confirmation. Do not call it an official Raspberry Pi display or a qualified BOM. Older indexed listing. |

Additional price checks rejected from the main shortlist:

- [Pi 4 4 GB + case/PSU, €80 VB](https://www.kleinanzeigen.de/s-anzeige/raspberry-pi-4b-4gb-inkl-gehaeuse-und-netzteil/3537166315-225-2559): case fan explicitly broken. Not a normal complete working comparison.
- [Pi 5 4 GB + Miuzei case/20 W PSU, €115 VB](https://www.kleinanzeigen.de/s-anzeige/raspberry-pi-5-4gb-ram-mit-miuzei-gehaeuse-20w-netzteil/3519683094-228-24242): Lübeck pickup only; 20 W does not establish the Pi 5's desired 5 V/5 A capability. No SD. Travel and possible replacement PSU erase some apparent saving.
- [Pi 4 8 GB + fan/case/SD, €120](https://www.kleinanzeigen.de/s-anzeige/raspberry-pi-4-model-b-8-gb-mit-gehaeuse-luefter-sd-karte-/3506818510-228-8561): shipping from €9.90; no PSU stated; body references different memory variants and an inconsistent model year. Inferior evidence and value.
- A €99 Munich Pi/display listing found during search was explicitly deleted/reserved. It must not be presented as available.

## New price references and availability caveats

| Item | Observed advertised price | Stock / interpretation |
| --- | --- | --- |
| [Welectron Pi 5 4 GB](https://www.welectron.com/Raspberry-Pi-5-4-GB-RAM) | **€118.00 incl. VAT** bare board | Parent page says 100+ and asks to choose variant. Its [exact Cooler Kit page](https://www.welectron.com/Raspberry-Pi-5-4-GB-Cooler-Kit) lists **all variants, including €118 board, as sold out**. Bare-board stock unresolved; do not report confirmed stock. |
| [Berrybase Pi 5 4 GB](https://www.berrybase.de/raspberry-pi-5-4gb-ram) | **€118.50 incl. VAT** | Direct page says **“Artikel aktuell nicht lieferbar”**, despite positive category/index snippets. Its accessory links show active cooler **€5.90** and official 27 W PSU **€12.40**. |
| [Welectron Pi 4 4 GB](https://www.welectron.com/Raspberry-Pi-4-Modell-B-4-GB-RAM) | **€107.00 incl. VAT** board | Parent page has variant selection/page-level stock, so exact board stock needs confirmation. Only €11 below the Pi 5 reference. |
| [Welectron Pi 4 8 GB Official Kit](https://www.welectron.com/Raspberry-Pi-4-B-8-GB-Official-Kit) | **€198.00 incl. VAT** exact kit | Listing says in stock, 1–3 days. Board, official case/PSU, heatsink, 1 m micro-HDMI cable; expensive and includes case/cable not needed for DSI custom enclosure. |
| [Official Pi 27 W PSU, Rasppishop](https://www.rasppishop.de/Raspberry-Pi-27W-USB-C-Netzteil-schwarz-EU) | **€12.40** | Explicit EU mains supply; prefer known 5.1 V/5 A specification over an unspecified used charger. |
| [Official Touch Display 2, Welectron](https://www.welectron.com/Offizielles-Raspberry-Pi-Touch-Display-2) | **€59.90 incl. VAT**, 7-inch SC1635 | Observed orderable with roughly three-week lead time; verify selected 7-inch variant. See the display recommendation above. |

Using the lowest observed board reference, **€118 + €12.40 + €5.90 + €59.90 = €196.20** for new Pi 5 4 GB + PSU + active cooler + official 7-inch screen, before shipping, panel extensions, printed enclosure and any hub. This is a conditional price reference because immediate board stock is unresolved. With the Berrybase board price it is €196.70, likewise unavailable there.

For the used Pi 4 €85 example, **€85 + €6.19 shipping + €8 estimated replacement PSU + €59.90 screen = €159.09**, before the screen's shipping and enclosure/ports/hub. That saves roughly €37 against the €196.20 new core, gives substantially less CPU headroom, and depends on an older private offer. A verifiable €130 board/screen bundle has stronger savings potential than used board-only shopping at these asking prices.

## Exact Chinese display alternatives

Manufacturer USD prices below are **not German landed EUR prices**. VAT treatment, shipping, selected variant and any import handling were not established at checkout. Direct Elecrow opens returned HTTP 403; its exact product pages and wiki were available in primary-source search results, generally indexed within the previous month. Waveshare's indexed prices were approximately two months old. These are concrete SKU/price leads, not live checkout quotations. AliExpress pages could not be reliably read; no promotional starting price or unverified AliExpress bargain is asserted.

### 1. Elecrow DLH05170B — inexpensive HDMI/USB option

[Manufacturer product](https://www.elecrow.com/7inch-ips-hd-touch-screen-d-1024-600-hd-monitor-compatible-with-raspberry-pi-bb-black-etc.html): **$36.90**, exact **7inch IPS HD Touch Screen-D**. Native **1024×600 IPS**, five-point capacitive GT911 touch, HDMI video and USB-C power/touch. A 1080p input claim does not make the panel 1080p. Listed dimensions 164.9×102×15.15 mm, 5 V/2.55 W. Box lists 1 m HDMI and USB-A-to-C cables, Pi 4/5 micro-HDMI adapter, mounting screws/standoffs and stand pieces; no PSU.

[Elecrow wiki](https://www.elecrow.com/wiki/7inch_IPS_HD_Touch_Screen-D.html) repeats the native resolution and power/interface specifications. Manufacturer claims driver-free Raspberry Pi/Ubuntu use; current OS, rotation, wake/reboot and Qt touch still need testing. HDMI and USB plugs add depth/strain-relief space; short replacement cables may be useful. **600 pixels of height requires a dedicated compact UI**, and touch consumes a USB data connection. Lowest observed manufacturer sticker price of the useful candidates.

### 2. Waveshare 7inch DSI LCD (E), SKU 29112 — best fit for the compact Pi concept

[Manufacturer product](https://www.waveshare.com/7inch-dsi-lcd-e.htm): **$62.99**, exact bare **7inch DSI LCD (E)**. Native **1280×800 IPS**, ten-point capacitive touch over I²C, optical bonding and toughened glass; DSI video. Pi 4/5 support is explicitly illustrated. [German Berrybase offer, WS-29112](https://www.berrybase.de/waveshare-7-zoll-dsi-touchdisplay-ips-1280x800-10-punkt-touch-i2c-fuer-raspberry-pi-5v): **€69.90 incl. VAT**, currently **unavailable**. Do not substitute its “In den Warenkorb” text for the actual unavailable status.

[Manufacturer wiki](https://www.waveshare.com/wiki/7inch_DSI_LCD_%28E%29) has **Trixie and Bookworm instructions** using the `vc4-kms-dsi-waveshare-panel` overlay and the `8_0_inch` parameter despite this being a 7-inch panel. Follow the exact model's instructions rather than infer another overlay. Pi 5 uses the included 12 cm DSI cable to the 22-pin DSI1 connector and power contacts/pogo arrangement. The package also lists 15-pin ribbons, power lead and mounting screws. [Mechanical drawing](https://files.waveshare.com/wiki/7inch-DSI-LCD-%28E%29/7inch_DSI_LCD_%28E%29-20250428.pdf) supports enclosure CAD; German retailer lists 170.18×104.20 mm outer dimensions and approximately 8 mm panel thickness. Check rear Pi/cooler clearances before printing. No USB data port is used by touch. Treat these documented setup steps as feasibility evidence, not our validation.

### 3. Elecrow DLH05270B — cheaper DSI, but low resolution

[Manufacturer product](https://www.elecrow.com/7inch-ips-dsi-touch-screen-a-800-480-monitor-compatible-with-raspberry-pi-bb-black-etc.html): **$42.90**, exact **7inch IPS DSI Touch Screen-A**, native **800×480 IPS**, five-point capacitive touch, 5 V/2.2 W; 192.96×110.76×20.13 mm. Pi 4/5 DSI is explicit. Package includes 5/10/20 cm Pi 4 ribbons, a **16 cm Pi 5 ribbon**, two-pin power cable and mounting hardware; no mains PSU.

The product page contains some inconsistent HDMI/USB marketing copy alongside its DSI-specific specification, so consult its model-specific wiring before purchase. **480-pixel height requires substantial UI redesign** and is a weak trade for a relatively modest saving versus the official €59.90 display. Its advertised Pi/Ubuntu compatibility is not an application/audio qualification.

Optional higher-resolution HDMI fallback: [Waveshare 7EP-CAPLCD, SKU 28996](https://www.waveshare.com/7ep-caplcd.htm), **$74.99** for the bare panel, **1280×800 IPS**, ten-point capacitive USB touch, HDMI and 5 V power. The **$84.99 “Monitor” variant is a different cased product**. Included HDMI/USB/micro-HDMI adapter and mounting/control parts are listed, but no PSU. It costs more than the DSI (E), adds USB/cable demand, and only makes sense if portability to a hidden/non-Pi host matters.
