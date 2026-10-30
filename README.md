# MSFS Universal Controller Mapper

Stop re-binding your controllers every time you load a different aircraft.

`msfs-mapper` detects the controllers on your USB ports, works out where they sit from a photo of
your setup, reads which aircraft is loaded in Microsoft Flight Simulator, and maps your
axes, buttons, switches and knobs to the functions that aircraft's **takeoff and landing
checklists** need. Mappings are saved per aircraft + hardware combination, so the next time you
load that aircraft they come back instantly.

## How it works

```
USB HID devices ──► device catalog (VID:PID) ──┐
setup photo ──► Claude vision (positions,      ├─► ControllerSetup
                 unknown devices)              ┘
                                                        │
MSFS (SimConnect) ──► AircraftInfo ──► checklist        ▼
                       template + Claude ──► AircraftProfile ──► mapper ──► MappingProfile
                                                                (heuristic + Claude, validated)
                                                                        │
USB input ──► Router ──► SimConnect key events ◄────────────────────────┘
```

1. **Recognise the hardware.** Controllers are enumerated through SDL (pygame) and matched to a
   catalog of known devices by USB vendor/product id (Honeycomb Alpha & Bravo, Logitech/Saitek
   throttle quadrant and rudder pedals, VKB Gladiator, T.16000M so far). Each catalog entry describes every control: its kind (axis, button,
   two-position switch, rotary encoder, hat), label and *role* (`gear`, `lights.landing`,
   `autopilot.hdg`...).
2. **Read the photo.** `scan-setup photo.jpg` sends the picture to Claude, which identifies the
   devices, where they sit relative to the seat, and any labels you stuck on them. Devices that are
   not in the catalog get a drafted control layout that you confirm with `learn`.
3. **Know the aircraft.** When an aircraft loads, its title, category, engine type/count and gear type
   are read over SimConnect. A checklist template (helicopter, single piston, turboprop, twin jet) gives the
   function list in priority order; Claude then tailors it to the specific aircraft and add-on
   (e.g. which functions a Fenix A320 drives differently).
4. **Map.** A deterministic scorer matches functions to controls by role, control kind and
   cockpit order (throttle → prop → mixture lands on levers 1 → 2 → 3). Claude refines that,
   and every binding it proposes is validated (control exists, kind compatible, no control used
   twice) before it is accepted. Bindings you `lock` are never changed.
5. **Fly.** `run` watches for aircraft changes, loads or builds the mapping, and forwards your
   input to the sim as SimConnect events.

## Quick start (Windows PC running MSFS 2020/2024)

```powershell
pip install -e ".[sim]"
setx ANTHROPIC_API_KEY "sk-ant-..."     # or `ant auth login`; use --no-ai to stay offline

msfs-mapper-gui                         # the window: everything below, point and click

msfs-mapper devices                     # what is plugged in, and what the catalog knows
msfs-mapper learn 1                     # once per device: confirm button/axis numbers
msfs-mapper scan-setup my-cockpit.jpg   # optional: positions + drafts for unknown devices
msfs-mapper import-mobiflight cockpit.mcc  # leave MobiFlight panels' functions to MobiFlight
msfs-mapper keyboard-knob --enable --drives hdg   # keyboard volume knob turns the heading bug
msfs-mapper map --title "Cessna 172" --engine-type 0     # preview a mapping offline
msfs-mapper map --title "Robinson R44" --category Helicopter
msfs-mapper --no-ai gui                # open the desktop mapping interface
msfs-mapper run --dry-run               # watch the sim, print what would be sent
msfs-mapper run                         # the real thing
msfs-mapper run --mobiflight-port COM5  # optional custom-firmware Mega input
```

On Windows, `install.bat` installs the simulator dependencies, `start_gui.bat` opens the offline
GUI, and `run_msfs.bat` starts the simulator runtime in dry-run mode. Pass `--live` as the first
argument to `run_msfs.bat` to send events to the simulator; other arguments are forwarded, e.g.
`run_msfs.bat --live --mobiflight-port COM5`.

### The window

`msfs-mapper-gui` (or `msfs-mapper gui`) opens one window with:

- **Hardware**: USB controllers with their catalog match, position and how many controls are
  verified, plus every imported MobiFlight panel.
- **Import MobiFlight project…**: pick your `.mcc` file. The *MobiFlight inputs* tab lists every
  input, what it does, and which function it was recognised as. Double-click an input to set or
  correct its function by hand.
- **Aircraft**: type a title or *Read from sim*, then *Build mapping* (*Rebuild* ignores the saved
  mapping but keeps locked bindings).
- **Mapping** tab: each function with the control assigned to it, functions MobiFlight handles,
  and functions with no free control. Select rows and *Lock / unlock* to pin them.
- **Keyboard knob…**: use the rotary/volume knob on your keyboard (see below).
- **Configure Mega pins…**: wiring for the custom-firmware Mega (see below).
- **Use Claude AI** switch: off = templates and heuristics only.

### Keyboard volume knob

Keyboards with a volume roller or rotary knob (Corsair, Logitech, Keychron, macro pads...) can
drive the sim as one more encoder. The knob is not a game controller: it sends keys, usually
*Volume Up / Volume Down / Mute*. While `msfs-mapper run` is running, a Windows keyboard hook
catches those keys even though MSFS has focus, and turns them into knob steps.

- **Turning drives**: *Automatic* (any free encoder function), or pin it to heading bug,
  selected altitude, selected vertical speed, elevator trim or flaps.
- **Pressing does**: nothing by default, so Mute keeps working; or autopilot master, AP disconnect,
  heading mode, altitude hold, parking brake.
- **Stop Windows changing the volume** (default on): the keys are swallowed only while the
  current aircraft's mapping actually uses the knob; otherwise your volume works as normal.
- Keys: *Volume Up/Down/Mute*, *Next/Previous track/Play-Pause*, or *F13/F14/F15* if your keyboard
  software lets you reprogram the knob (keeps it separate from your real media keys).

Set it up in the window (*Keyboard knob…*) or with
`msfs-mapper keyboard-knob --enable --keys volume --drives hdg --press ap`.

### MobiFlight Connector projects

MobiFlight boards are Arduinos on a serial port, so they never show up as game controllers.
Importing your MobiFlight Connector project (`.mcc`) tells the mapper what they already do:

- each input's commands (`(>K:GEAR_DOWN)`, event ids, presets) are matched to the function
  catalog; with AI on, Claude identifies the rest (add-on L:vars, H:events);
- functions a MobiFlight input already operates are **left to MobiFlight** by default: they are
  not mapped a second time onto your Bravo or Alpha. Two controls for one function can disagree
  (panel gear switch DOWN, Bravo gear lever UP), and skipping them frees controls for functions
  that would otherwise have none;
- optionally (*Also map MobiFlight buttons and knobs…* in the window, `--share-buttons` on the
  command line) functions of MobiFlight **buttons and knobs** may also go on one of your buttons
  or knobs, e.g. a heading knob on both the panel and the Bravo. Inputs that hold a position
  (toggle switches acting on press *and* release, analog levers) are never doubled, and a shared
  function never lands on a switch or lever of yours;
- joysticks that MobiFlight reads directly (serial `JS-…`, e.g. a Bravo button you configured in
  MobiFlight) have those buttons reserved, so the same button never fires two actions.

MobiFlight keeps running your boards; your own `.mcc` file is never modified. A saved mapping is
rebuilt automatically when the import changes.

### Exporting the mapping to MobiFlight (on by default)

Each time a mapping is built, it is also written into a MobiFlight project:
`~/.msfs-mapper/mobiflight/<your project> - <aircraft>.mcc`. That file is a copy of your imported
project (boards, outputs, your inputs untouched) plus one input config per mapped control, tagged
`[msfs-mapper]` in the description. Load it in MobiFlight Connector and MobiFlight runs those
controls; `msfs-mapper run` then leaves them alone, so nothing is sent twice. MobiFlight can also
send add-on aircraft L:vars / H:events, which the built-in bridge can't yet.

- Only controllers MobiFlight already knows are exported. MobiFlight identifies a joystick by an id
  that can't be read from USB, so it is learned from your project: configure any one input of a
  controller in MobiFlight once, save, re-import, and that controller is exported from then on.
- Not exported (kept by `msfs-mapper run`): the keyboard knob, hats, and axes that need
  calculator code.
- Re-exporting replaces the previous `[msfs-mapper]` configs; importing the exported file ignores
  them, so the two never feed back into each other.
- Turn it off with the checkbox on the *MobiFlight inputs* tab or `msfs-mapper mobiflight-export
  --off`; `--folder` changes where projects are written.

### MobiFlight Mega (custom firmware)

The optional direct Mega input is a separate path from stock MobiFlight Connector: it requires
the companion sketch at `src/msfs_mapper/data/firmware/mobiflight_mega/mobiflight_mega.ino`
(also included in the installed package). Configure button/encoder pins in the desktop GUI and
close MobiFlight Connector before opening the Mega's COM port. The sketch reports button
press/release and encoder turns over USB
serial at 115200 baud. By default it uses 8 buttons on pins 22-29 and 2 encoders on pins 2/3 and
18/19. The Mega supports up to 32 buttons and 3 encoders (the three interrupt-capable pin pairs
are 2/3, 18/19, and 20/21).

Pass counts matching the sketch when starting the mapper, for example:

```powershell
msfs-mapper run --mobiflight-port COM5 --mobiflight-buttons 8 --mobiflight-encoders 2 --dry-run
```

Use **Configure Mega pins** in the desktop GUI to edit and save the wiring to
`%USERPROFILE%\.msfs-mapper\mobiflight_mega.json`. Then run `upload_mobiflight.bat COM5` (or omit
the port to be prompted). The script uses Arduino CLI from PATH or the copy bundled with Arduino
IDE 2, generates a matching firmware header from the saved JSON, and uploads for an Arduino Mega
2560. This script does not install Arduino IDE or its AVR board core. If you change the number of
buttons or encoders, also pass matching `--mobiflight-buttons` and `--mobiflight-encoders` values
when running the mapper.

The first version handles buttons and rotary encoders as mapper inputs; it does not support Mega
analog inputs or drive displays/LEDs. Profiles for a Mega with different input counts are stored
separately.

Because `msfs-mapper` drives the sim itself, **clear the bindings for these devices in the MSFS
controls menu** (an empty profile per device) so the two don't fight.

Saved data lives in `~/.msfs-mapper` (override with `--home` or `MSFS_MAPPER_HOME`):
`mappings/` per aircraft and hardware set, `aircraft/` cached aircraft profiles, `devices/` learned
or drafted device definitions, `positions.json` from the photo scan, `mobiflight.json` the imported
MobiFlight inputs, `keyboard.json` the keyboard knob settings. Mappings are plain JSON —
set `"locked": true` on a binding to pin it.

## Status

This is an early scaffold. What works and what doesn't yet:

| Area | State |
| --- | --- |
| Mapping engine, AI refinement + validation, profile storage | Implemented, unit-tested |
| Desktop window (tkinter) | Implemented, tested under a virtual display |
| MobiFlight `.mcc` import | Implemented and tested against a **hand-written** sample project; not yet checked against a real exported `.mcc` |
| MobiFlight joystick button numbering (`Button N` → SDL index N-1) | Assumed, unverified |
| MobiFlight export | Written and tested against the format as known; joystick input names (`Button N`, `Axis X`...) and the axis value range are **unverified** until opened in MobiFlight |
| Keyboard volume knob | Key decoding, mapping and window tested; the Windows keyboard hook itself is **not yet run on Windows** |
| Function catalog (≈40 functions, standard SimConnect key events) | Implemented |
| Checklist templates: helicopter, single piston, turboprop, twin jet | Implemented; glider missing |
| Device catalog: Alpha, Bravo, Saitek pedals, T.16000M | **Button indices from community references, unverified** — run `learn` |
| Logitech/Saitek Pro Flight Throttle Quadrant | 3 axes + 6 buttons cataloged; indices unverified — run `learn` |
| VKB Gladiator NXT/EVO | Stick, twist, throttle, mini-stick, POV hat and buttons cataloged; indices unverified — run `learn` |
| MobiFlight Mega custom-firmware input | Buttons and encoders over USB serial; sketch and mapper path included |
| SDL input, SimConnect aircraft detection and event sending | Written, **not yet run against real hardware/sim** |
| Add-on aircraft L:vars / H:events (calculator code) | Modelled; sending needs the MobiFlight WASM module, not wired up |
| Reading or writing MSFS's own input profiles | Not planned for now (we act as the bridge instead) |
| Switch state sync (toggle-only events can drift from the sim) | Not yet; prefer functions with explicit on/off events |

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests use a fake Claude client and scripted input events, so they run anywhere (no Windows,
sim, hardware, or API key needed). The GUI tests need Tk and a display; on a headless Linux box run
`xvfb-run -a pytest`, otherwise they are skipped. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
module layout and how to add devices, functions and templates.
