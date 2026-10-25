# Repository instructions

## Build and test

- Install development dependencies with `python -m pip install -e ".[dev]"`.
- Run the full test suite with `python -m pytest`.
- Run one test with `python -m pytest tests/test_mapping.py::test_single_piston_on_alpha_bravo_pedals`; replace the file and test name to target another test.
- Install Windows simulator/runtime dependencies with `python -m pip install -e ".[sim]"`. The `sim` extra includes pygame, pyserial, and SimConnect.
- There is no lint or formatter configured in `pyproject.toml`.
- Tests use fake Claude clients and scripted controller events; they do not require MSFS, hardware, or an API key.

## Architecture

The CLI in `src/msfs_mapper/cli.py` connects the stages; `gui.py` provides a Tkinter desktop interface over the same mapping pipeline. `devices/discovery.py` enumerates SDL controllers and joins USB vendor/product IDs to the built-in catalog and user definitions from the mapper home directory. Device and simulator concepts are shared through Pydantic models in `models.py`.

Aircraft detection reads SimConnect data; `aircraft/templates.py` chooses a checklist template and `aircraft/knowledge.py` optionally asks Claude to tailor aircraft functions. The `pipeline.Mapper` builds a controller setup and loads or generates aircraft and mapping profiles. `mapping/engine.py` creates deterministic role/kind-compatible mappings; `mapping/ai_mapper.py` accepts only valid Claude proposals and fills gaps from the heuristic. `profiles/store.py` persists aircraft profiles and mappings keyed by aircraft and hardware fingerprint.

At runtime, input sources produce events consumed by `runtime/bridge.py`'s `Router`, which maps physical controls to `SimAction`s and sends them through either the dry-run logger or SimConnect executor. SDL controllers use pygame. The optional MobiFlight Mega path is separate: `devices/mobiflight.py` builds a definition, `runtime/inputs.py` reads the companion custom firmware's serial protocol, and its sketch is under `data/firmware/`. Pin configuration is validated and stored as JSON by `firmware_config.py`; the GUI edits it and `upload_mobiflight.bat` generates the Arduino header before upload.

## Repository conventions

- Built-in devices, functions, and aircraft checklists are YAML package data. Device definitions are keyed by USB VID:PID; user JSON definitions override built-ins. A device definition lists controls in meaningful physical/cockpit order because that order is a mapping tie-breaker, and each control's `roles` and `kind` drive compatibility. Treat preset HID indices as unverified unless confirmed; `msfs-mapper learn <index>` persists verified user definitions.
- Keep control and function IDs stable: saved bindings reference those IDs. Hardware combinations are fingerprinted to keep mappings isolated.
- Function actions are declared by input kind (`axis`, `press`, `on`/`off`, `inc`/`dec`) in `data/functions.yaml`. Use standard SimConnect event names for events and `{calc: "..."}` for calculator actions. YAML 1.1 parses bare `on` and `off` keys as booleans; `data/__init__.py` normalizes them when loading.
- AI output is a proposal, not authoritative data. Preserve the compatibility, control/function uniqueness, locked-binding, and heuristic-backfill checks in the mapping merge path. AI failures should continue to leave the offline heuristic usable.
- When adding packaged files, update `[tool.setuptools.package-data]` in `pyproject.toml` if their file pattern is not already included. The firmware sketch is explicitly packaged.
- Optional simulator imports are kept inside runtime entry points so catalog, mapping, and unit tests can run without Windows simulator dependencies.
