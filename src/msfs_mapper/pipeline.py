"""Glue: detected hardware + loaded aircraft -> cached or freshly generated mapping."""

from __future__ import annotations

import logging
from pathlib import Path

from msfs_mapper.ai import AIError, Claude
from msfs_mapper.aircraft.knowledge import advise
from msfs_mapper.aircraft.templates import profile_from_template
from msfs_mapper.data import function_catalog
from msfs_mapper.devices.catalog import DeviceCatalog
from msfs_mapper.devices.discovery import build_setup
from msfs_mapper.mapping.ai_mapper import ai_map
from msfs_mapper.mapping.engine import functions_for, heuristic_map
from msfs_mapper.mobiflight import ai_identify, import_project
from msfs_mapper.mobiflight_export import ExportResult, export_path, export_project, split
from msfs_mapper.models import (
    AircraftInfo,
    AircraftProfile,
    ControllerSetup,
    DetectedDevice,
    MappingProfile,
    MobiFlightImport,
)
from msfs_mapper.profiles.store import Store

log = logging.getLogger(__name__)


class Mapper:
    def __init__(self, store: Store, claude: Claude | None = None):
        self.store = store
        self.claude = claude
        self.catalog = DeviceCatalog(store.devices_dir)
        self.last_export: ExportResult | None = None

    def setup(self, detected: list[DetectedDevice]) -> ControllerSetup:
        setup = build_setup(detected, self.catalog)
        knob = self.store.load_keyboard()
        if knob.enabled:
            from msfs_mapper.runtime.keyboard import knob_device

            # First, so a role the user picked for the knob wins ties against other encoders.
            setup.devices.insert(0, knob_device(knob))
        positions = self.store.load_positions()
        for device in setup.devices:
            device.position = positions.get(device.key, device.position)
        return setup

    def scan_photo(self, photo: Path, detected: list[DetectedDevice]) -> tuple[ControllerSetup, list[str]]:
        """Place devices from a setup photo and draft definitions for unknown ones. Returns messages."""
        from msfs_mapper.vision.layout import analyse_setup_photo, apply_photo, draft_unknown_device

        if self.claude is None:
            raise AIError("scanning a photo needs the Claude API (AI is switched off)")
        setup = self.setup(detected)
        seen = analyse_setup_photo(self.claude, photo, detected)
        messages = [
            f"seen in photo but not on USB: {s.manufacturer} {s.model} ({s.position})"
            for s in apply_photo(setup, seen)
        ]
        self.store.save_positions({d.key: d.position for d in setup.devices})
        if seen.notes:
            messages.append(f"notes: {seen.notes}")
        for device in setup.devices:
            if device.definition is None and device.detected.usb_id:
                definition = draft_unknown_device(self.claude, device.detected, photo)
                self.catalog.save(definition)
                device.definition = definition
                messages.append(
                    f"drafted {len(definition.controls)} controls for {device.detected.name}"
                    f" (confirm with: msfs-mapper learn {device.detected.index})"
                )
        return setup, messages

    def import_mobiflight(
        self, path: Path, setup: ControllerSetup, profile: AircraftProfile | None = None
    ) -> MobiFlightImport:
        """Parse a MobiFlight project, recognise its inputs (AI for the leftovers) and save it."""
        functions = functions_for(profile) if profile else function_catalog()
        imported = import_project(path, functions, setup)
        previous = self.store.load_mobiflight()
        if previous:  # re-importing keeps the user's sharing choice
            imported = imported.model_copy(update={"allow_shared": previous.allow_shared})
        if self.claude:
            try:
                imported = ai_identify(self.claude, imported, functions)
            except AIError as exc:
                log.warning("AI identification of MobiFlight inputs failed: %s", exc)
        self.store.save_mobiflight(imported)
        return imported

    def set_mobiflight_sharing(self, allow: bool) -> MobiFlightImport | None:
        """Let MobiFlight buttons and knobs also be mapped to our own buttons and knobs."""
        imported = self.store.load_mobiflight()
        if imported is not None:
            imported = imported.model_copy(update={"allow_shared": allow})
            self.store.save_mobiflight(imported)
        return imported

    def aircraft_profile(self, aircraft: AircraftInfo, refresh: bool = False) -> AircraftProfile:
        cached = None if refresh else self.store.load_aircraft(aircraft.key)
        if cached:
            return cached
        profile = profile_from_template(aircraft)
        if self.claude:
            try:
                profile = advise(self.claude, aircraft)
            except AIError as exc:
                log.warning("AI aircraft analysis failed, using %s template: %s", profile.template, exc)
                return profile  # don't cache the fallback, so the AI is retried next time
        self.store.save_aircraft(profile)
        return profile

    def mapping(
        self, setup: ControllerSetup, profile: AircraftProfile, refresh: bool = False
    ) -> MappingProfile:
        previous = self.store.load_mapping(profile.aircraft.key, setup.fingerprint())
        external = self.store.load_mobiflight()
        handled = external.handled_functions() if external else set()
        sharing = external.allow_shared if external else False
        if (
            previous and not refresh
            and {b.function for b in previous.external} == handled
            and previous.external_shared == sharing
        ):
            self.export_mobiflight(setup, profile, previous)
            return previous
        mapping = None
        if self.claude:
            try:
                mapping = ai_map(self.claude, setup, profile, previous, external)
            except AIError as exc:
                log.warning("AI mapping failed, using heuristic mapping: %s", exc)
        mapping = mapping or heuristic_map(setup, profile, previous, external)
        self.store.save_mapping(mapping)
        self.export_mobiflight(setup, profile, mapping)
        return mapping

    def export_mobiflight(
        self, setup: ControllerSetup, profile: AircraftProfile, mapping: MappingProfile
    ) -> ExportResult | None:
        """Write the mapping into a MobiFlight project, if the export setting is on."""
        settings = self.store.load_settings()
        self.last_export = None
        if not settings.export_mobiflight:
            return None
        imported = self.store.load_mobiflight()
        folder = Path(settings.export_folder) if settings.export_folder else self.store.home / "mobiflight"
        target = export_path(folder, imported, profile.aircraft.title)
        try:
            self.last_export = export_project(setup, mapping, functions_for(profile), imported, target)
        except OSError as exc:
            log.warning("could not write MobiFlight project %s: %s", target, exc)
        return self.last_export

    def routed_mapping(
        self, setup: ControllerSetup, profile: AircraftProfile, mapping: MappingProfile
    ) -> MappingProfile:
        """The bindings `run` must drive itself: everything not handed to MobiFlight."""
        if not self.store.load_settings().export_mobiflight:
            return mapping
        result = split(setup, mapping, functions_for(profile), self.store.load_mobiflight())
        return mapping.model_copy(update={"bindings": result.kept})
