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
   catalog of known devices by USB vendor/product id (Honeycomb Alpha & Bravo, Saitek pedals,
   T.16000M so far). Each catalog entry describes every control: its kind (axis, button,
   two-position switch, rotary encoder, hat), label and *role* (`gear`, `lights.landing`,
   `autopilot.hdg`...).
2. **Read the photo.** `scan-setup photo.jpg` sends the picture to Claude, which identifies the
   devices, where they sit relative to the seat, and any labels you stuck on them. Devices that are
   not in the catalog get a drafted control layout that you confirm with `learn`.
3. **Know the aircraft.** When an aircraft loads, its title, engine type/count and gear type are
   read over SimConnect. A checklist template (single piston, turboprop, twin jet) gives the
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
msfs-mapper map --title "Cessna 172" --engine-type 0     # preview a mapping offline
msfs-mapper run --dry-run               # watch the sim, print what would be sent
msfs-mapper run                         # the real thing
```

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
- **Use Claude AI** switch: off = templates and heuristics only.

### MobiFlight panels

MobiFlight boards are Arduinos on a serial port, so they never show up as game controllers.
Importing your MobiFlight Connector project (`.mcc`) tells the mapper what they already do:

- each input's commands (`(>K:GEAR_DOWN)`, event ids, presets) are matched to the function
  catalog; with AI on, Claude identifies the rest (add-on L:vars, H:events);
- functions a MobiFlight input already operates are **left to MobiFlight**: they are not mapped a
  second time onto your Bravo or Alpha;
- joysticks that MobiFlight reads directly (serial `JS-…`, e.g. a Bravo button you configured in
  MobiFlight) have those buttons reserved, so the same button never fires two actions.

MobiFlight keeps running your boards; nothing is written to your `.mcc` file. A saved mapping is
rebuilt automatically when the import changes.

Because `msfs-mapper` drives the sim itself, **clear the bindings for these devices in the MSFS
controls menu** (an empty profile per device) so the two don't fight.

Saved data lives in `~/.msfs-mapper` (override with `--home` or `MSFS_MAPPER_HOME`):
`mappings/` per aircraft and hardware set, `aircraft/` cached aircraft profiles, `devices/` learned
or drafted device definitions, `positions.json` from the photo scan, `mobiflight.json` the imported
MobiFlight inputs. Mappings are plain JSON —
set `"locked": true` on a binding to pin it.

## Status

This is an early scaffold. What works and what doesn't yet:

| Area | State |
| --- | --- |
| Mapping engine, AI refinement + validation, profile storage | Implemented, unit-tested |
| Desktop window (tkinter) | Implemented, tested under a virtual display |
| MobiFlight `.mcc` import | Implemented and tested against a **hand-written** sample project; not yet checked against a real exported `.mcc` |
| MobiFlight joystick button numbering (`Button N` → SDL index N-1) | Assumed, unverified |
| Function catalog (≈40 functions, standard SimConnect key events) | Implemented |
| Checklist templates: single piston, turboprop, twin jet | Implemented; helicopter/glider missing |
| Device catalog: Alpha, Bravo, Saitek pedals, T.16000M | **Button indices from community references, unverified** — run `learn` |
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
