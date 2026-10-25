"""Glue: detected hardware + loaded aircraft -> cached or freshly generated mapping."""

from __future__ import annotations

import logging

from msfs_mapper.ai import AIError, Claude
from msfs_mapper.aircraft.knowledge import advise
from msfs_mapper.aircraft.templates import profile_from_template
from msfs_mapper.devices.catalog import DeviceCatalog
from msfs_mapper.devices.discovery import build_setup
from msfs_mapper.mapping.ai_mapper import ai_map
from msfs_mapper.mapping.engine import heuristic_map
from msfs_mapper.models import (
    AircraftInfo,
    AircraftProfile,
    ControllerSetup,
    DetectedDevice,
    MappingProfile,
)
from msfs_mapper.profiles.store import Store

log = logging.getLogger(__name__)


class Mapper:
    def __init__(self, store: Store, claude: Claude | None = None):
        self.store = store
        self.claude = claude
        self.catalog = DeviceCatalog(store.devices_dir)

    def setup(self, detected: list[DetectedDevice]) -> ControllerSetup:
        setup = build_setup(detected, self.catalog)
        positions = self.store.load_positions()
        for device in setup.devices:
            device.position = positions.get(device.key, device.position)
        return setup

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
        if previous and not refresh:
            return previous
        mapping = None
        if self.claude:
            try:
                mapping = ai_map(self.claude, setup, profile, previous)
            except AIError as exc:
                log.warning("AI mapping failed, using heuristic mapping: %s", exc)
        mapping = mapping or heuristic_map(setup, profile, previous)
        self.store.save_mapping(mapping)
        return mapping
