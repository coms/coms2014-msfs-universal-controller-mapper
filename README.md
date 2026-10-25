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

msfs-mapper devices                     # what is plugged in, and what the catalog knows
msfs-mapper learn 1                     # once per device: confirm button/axis numbers
msfs-mapper scan-setup my-cockpit.jpg   # optional: positions + drafts for unknown devices
msfs-mapper map --title "Cessna 172" --engine-type 0     # preview a mapping offline
msfs-mapper --no-ai gui                # open the desktop mapping interface
msfs-mapper run --dry-run               # watch the sim, print what would be sent
msfs-mapper run                         # the real thing
msfs-mapper run --mobiflight-port COM5  # optional custom-firmware Mega input
```

On Windows, `install.bat` installs the simulator dependencies, `start_gui.bat` opens the offline
GUI, and `run_msfs.bat` starts the simulator runtime in dry-run mode. Pass `--live` as the first
argument to `run_msfs.bat` to send events to the simulator; other arguments are forwarded, e.g.
`run_msfs.bat --live --mobiflight-port COM5`.

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
or drafted device definitions, `positions.json` from the photo scan. Mappings are plain JSON —
set `"locked": true` on a binding to pin it.

## Status

This is an early scaffold. What works and what doesn't yet:

| Area | State |
| --- | --- |
| Mapping engine, AI refinement + validation, profile storage | Implemented, unit-tested |
| Function catalog (≈40 functions, standard SimConnect key events) | Implemented |
| Checklist templates: single piston, turboprop, twin jet | Implemented; helicopter/glider missing |
| Device catalog: Alpha, Bravo, Saitek pedals, T.16000M | **Button indices from community references, unverified** — run `learn` |
| Logitech/Saitek Pro Flight Throttle Quadrant | 3 axes + 6 buttons cataloged; indices unverified — run `learn` |
| VKB Gladiator NXT/EVO | Stick, twist, throttle, mini-stick, POV hat and buttons cataloged; indices unverified — run `learn` |
| MobiFlight Mega custom-firmware input | Buttons and encoders over USB serial; sketch and mapper path included |
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
sim, hardware, or API key needed). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
module layout and how to add devices, functions and templates.
