# Architecture

## Modules

| Module | Responsibility |
| --- | --- |
| `models.py` | Pydantic data model shared by every stage |
| `data/` | Bundled YAML: `functions.yaml`, `checklists/*.yaml`, `devices/*.yaml` |
| `devices/discovery.py` | SDL enumeration, SDL GUID → USB VID/PID, join with the catalog |
| `devices/catalog.py` | Built-in device definitions overlaid with user ones (`~/.msfs-mapper/devices`) |
| `vision/layout.py` | Claude vision: device positions from a photo, drafts for unknown devices |
| `aircraft/detect.py` | SimConnect polling of TITLE / ENGINE TYPE / gear etc., change detection |
| `aircraft/templates.py` | Pick a checklist template, filter functions for the airframe |
| `aircraft/knowledge.py` | Claude tailors the template to the specific aircraft/add-on |
| `mapping/engine.py` | Deterministic scorer + greedy assignment; also the compatibility validator |
| `mapping/ai_mapper.py` | Claude proposes a mapping; `merge` validates and back-fills from the heuristic |
| `profiles/store.py` | JSON persistence, keyed by aircraft and hardware fingerprint |
| `runtime/bridge.py` | Input event → SimAction routing; SimConnect and dry-run executors |
| `runtime/keyboard.py` | Keyboard knob as a virtual encoder device; Windows low-level keyboard hook |
| `runtime/learn.py` | Interactive index confirmation for device definitions |
| `mobiflight.py` | Parse MobiFlight `.mcc` projects, recognise input functions, link `JS-` joystick inputs |
| `mobiflight_export.py` | Write mappings into a copy of the MobiFlight project; `split` decides what MobiFlight runs |
| `pipeline.py` | Cache-or-generate orchestration, AI with offline fallback |
| `cli.py` | `devices`, `scan-setup`, `import-mobiflight`, `learn`, `map`, `run`, `gui` |
| `gui.py` | tkinter window; slow work on a worker thread, results marshalled back with `after` |

## Design decisions

- **The AI never has the last word.** Every binding Claude proposes goes through
  `engine.is_compatible` and uniqueness checks; anything invalid is dropped and the heuristic
  fills the gap. If the API is unreachable the heuristic mapping is used and the AI is retried
  on the next load.
- **Roles, not button numbers, carry meaning.** Device definitions say *what a control is for*
  (`gear`, `lights.landing`); functions say which roles they accept. Generic roles (`switch`,
  `lever`, `encoder`) let spare hardware absorb leftover functions; a control with a specific
  purpose is never repurposed by the heuristic.
- **Cockpit order is data.** Template function lists put axis functions in left-to-right cockpit
  order and device definitions list levers left to right; the stable tie-break preserves it.
- **MobiFlight stays in charge of its own panels.** An import produces `ExternalBinding`s; the
  functions they operate are skipped by both mappers and listed in `MappingProfile.external`, and
  joystick buttons MobiFlight reads are removed from the free slots. With `allow_shared`, functions
  of momentary inputs (`maintained=False`) are mapped again, restricted to `MOMENTARY` control
  kinds; maintained inputs stay exclusive. The router never sends
  anything for external bindings.
- **The keyboard knob is just another device.** It enters the setup as a virtual device
  (index -1) whose controls carry the role the user picked, so the normal mapper assigns it. It is
  placed first so a picked role wins ties against other encoders. The hook swallows a key only
  while the router has a binding for it.
- **Export and run agree on who drives what.** `mobiflight_export.split` is the single decision:
  the exporter writes exactly its `exported` list and `Mapper.routed_mapping` gives `run` exactly
  its `kept` list. Generated configs are tagged so import ignores them and export replaces them.
- **One mapping per (aircraft, hardware set).** Plugging in a different combination of devices
  produces a separate mapping instead of corrupting the existing one.
- **Claude calls** use structured outputs (pydantic models) with adaptive thinking and
  server-side refusal fallback; see `ai.py`.

## Extending

- **New device:** add `data/devices/<name>.yaml` (or let `scan-setup` draft one), then run
  `msfs-mapper learn <index>` to verify indices. Learned definitions are saved to the user
  catalog and override the built-in one.
- **New function:** add an entry to `data/functions.yaml` with its roles, preferred control kinds
  and the SimConnect events for each action (`axis`, `press`, `on`/`off`, `inc`/`dec`). Use
  `{calc: "..."}` for calculator code.
- **New aircraft class:** add `data/checklists/<id>.yaml` and teach `choose_template` when to
  pick it.
