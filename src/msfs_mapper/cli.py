"""Command line entry point: `msfs-mapper --help`."""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import threading
from pathlib import Path

from msfs_mapper.ai import AIError, Claude
from msfs_mapper.mapping.engine import functions_for
from msfs_mapper.models import AircraftInfo, AircraftProfile, ControllerSetup, MappingProfile
from msfs_mapper.pipeline import Mapper
from msfs_mapper.profiles.store import Store


def _detect():
    from msfs_mapper.devices.discovery import PygameBackend

    return PygameBackend().list_devices()


def _mapper(args: argparse.Namespace) -> Mapper:
    return Mapper(Store(args.home), None if args.no_ai else Claude())


def cmd_devices(args: argparse.Namespace) -> int:
    setup = _mapper(args).setup(_detect())
    if not setup.devices:
        print("No game controllers found.")
    for d in setup.devices:
        known = f"-> {d.definition.manufacturer} {d.definition.name}" if d.definition else "-> not in catalog"
        verified = sum(c.verified for c in d.controls)
        print(f"[{d.detected.index}] {d.detected.name} (USB {d.detected.usb_id or '?'}) {known}")
        print(f"     {d.detected.num_axes} axes, {d.detected.num_buttons} buttons, {d.detected.num_hats} hats;"
              f" position {d.position}; {verified}/{len(d.controls)} controls verified")
    return 0


def cmd_scan_setup(args: argparse.Namespace) -> int:
    from msfs_mapper.vision.layout import analyse_setup_photo, apply_photo, draft_unknown_device

    mapper = Mapper(Store(args.home), Claude())
    detected = _detect()
    setup = mapper.setup(detected)
    photo = analyse_setup_photo(mapper.claude, args.photo, detected)
    unmatched = apply_photo(setup, photo)
    mapper.store.save_positions({d.key: d.position for d in setup.devices})
    for d in setup.devices:
        print(f"{d.detected.name}: {d.position}")
    for seen in unmatched:
        print(f"seen in photo but not on USB: {seen.manufacturer} {seen.model} ({seen.position})")
    if photo.notes:
        print(f"notes: {photo.notes}")
    for d in setup.devices:
        if d.definition is None and d.detected.usb_id:
            definition = draft_unknown_device(mapper.claude, d.detected, args.photo)
            path = mapper.catalog.save(definition)
            print(f"drafted {len(definition.controls)} controls for {d.detected.name} -> {path}"
                  f" (confirm with: msfs-mapper learn {d.detected.index})")
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    from msfs_mapper.runtime.inputs import PygameInputSource
    from msfs_mapper.runtime.learn import learn_device

    mapper = Mapper(Store(args.home))
    device = next((d for d in mapper.setup(_detect()).devices if d.detected.index == args.index), None)
    if device is None or device.definition is None:
        print("Device not found or not in catalog; run `scan-setup` first to draft a definition.")
        return 1
    source = PygameInputSource()
    learned = learn_device(device.definition, args.index, lambda t: source.events(timeout=t))
    print(f"saved {mapper.catalog.save(learned)}")
    return 0


def _aircraft_from_args(args: argparse.Namespace) -> AircraftInfo:
    if args.title:
        return AircraftInfo(
            title=args.title, engine_type=args.engine_type, engine_count=args.engines,
            retractable_gear=args.retractable,
        )
    from msfs_mapper.aircraft.detect import SimConnectAircraftSource

    info = SimConnectAircraftSource().read()
    if info is None:
        raise SystemExit("No aircraft loaded in the sim (or pass --title)")
    return info


def print_mapping(setup: ControllerSetup, profile: AircraftProfile, mapping: MappingProfile) -> None:
    functions = functions_for(profile)
    names = {d.key: d.detected.name for d in setup.devices}
    print(f"\n{profile.aircraft.title}  [{profile.template}, mapped by {mapping.source}]")
    for b in mapping.bindings:
        lock = " (locked)" if b.locked else ""
        print(f"  {functions[b.function].name:<32} <- {names.get(b.device, b.device)} / {b.control}{lock}")
    if mapping.unassigned_functions:
        print("  no free control for: " + ", ".join(mapping.unassigned_functions))
    if profile.notes:
        print(f"  notes: {profile.notes}")


def cmd_map(args: argparse.Namespace) -> int:
    mapper = _mapper(args)
    setup = mapper.setup(_detect())
    profile = mapper.aircraft_profile(_aircraft_from_args(args), refresh=args.refresh)
    mapping = mapper.mapping(setup, profile, refresh=args.refresh)
    print_mapping(setup, profile, mapping)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from SimConnect import SimConnect

    from msfs_mapper.aircraft.detect import SimConnectAircraftSource, watch_aircraft
    from msfs_mapper.runtime.bridge import LogExecutor, Router, SimConnectExecutor
    from msfs_mapper.runtime.inputs import PygameInputSource

    mapper = _mapper(args)
    sim = SimConnect()
    source = PygameInputSource()
    setup = mapper.setup(_detect())
    executor = LogExecutor() if args.dry_run else SimConnectExecutor(sim)
    loaded: queue.Queue[AircraftInfo] = queue.Queue()
    aircraft_source = SimConnectAircraftSource(sim)

    def watcher() -> None:
        for info in watch_aircraft(aircraft_source.read):
            loaded.put(info)

    threading.Thread(target=watcher, daemon=True).start()
    print("Waiting for an aircraft to load... (Ctrl+C to quit)")
    router = None
    try:
        while True:
            try:
                info = loaded.get_nowait()
                profile = mapper.aircraft_profile(info)
                mapping = mapper.mapping(setup, profile)
                print_mapping(setup, profile, mapping)
                router = Router(setup, mapping, functions_for(profile), executor)
            except queue.Empty:
                pass
            for event in source.events(timeout=0.5):
                if router:
                    router.handle(event)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="msfs-mapper", description=__doc__)
    parser.add_argument("--home", type=Path, default=None, help="data directory (default ~/.msfs-mapper)")
    parser.add_argument("--no-ai", action="store_true", help="offline: templates and heuristics only")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list connected controllers and catalog matches").set_defaults(fn=cmd_devices)

    p = sub.add_parser("scan-setup", help="locate devices from a photo of your setup")
    p.add_argument("photo", type=Path)
    p.set_defaults(fn=cmd_scan_setup)

    p = sub.add_parser("learn", help="confirm a device's button/axis indices interactively")
    p.add_argument("index", type=int, help="device index from `devices`")
    p.set_defaults(fn=cmd_learn)

    p = sub.add_parser("map", help="build (or show the saved) mapping for an aircraft")
    p.add_argument("--title", help="aircraft title; omit to read it from the running sim")
    p.add_argument("--engine-type", type=int, default=0, help="0 piston, 1 jet, 5 turboprop")
    p.add_argument("--engines", type=int, default=1)
    p.add_argument("--retractable", action="store_true", help="retractable landing gear")
    p.add_argument("--refresh", action="store_true", help="regenerate even if a mapping is saved")
    p.set_defaults(fn=cmd_map)

    p = sub.add_parser("run", help="auto-map each aircraft as it loads and drive the sim")
    p.add_argument("--dry-run", action="store_true", help="log actions instead of sending them")
    p.set_defaults(fn=cmd_run)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    try:
        return args.fn(args)
    except AIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
