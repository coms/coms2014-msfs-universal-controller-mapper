"""Everything the tool remembers lives under one directory (MSFS_MAPPER_HOME or ~/.msfs-mapper)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from msfs_mapper.models import AircraftProfile, KeyboardKnob, MappingProfile, MobiFlightImport, Settings


def default_home() -> Path:
    return Path(os.environ.get("MSFS_MAPPER_HOME", Path.home() / ".msfs-mapper"))


class Store:
    def __init__(self, home: Path | None = None):
        self.home = home or default_home()

    @property
    def devices_dir(self) -> Path:
        return self.home / "devices"

    def _mapping_path(self, aircraft_key: str, fingerprint: str) -> Path:
        digest = hashlib.sha1(fingerprint.encode()).hexdigest()[:10]
        return self.home / "mappings" / f"{aircraft_key}__{digest}.json"

    def _aircraft_path(self, aircraft_key: str) -> Path:
        return self.home / "aircraft" / f"{aircraft_key}.json"

    def load_positions(self) -> dict[str, str]:
        path = self.home / "positions.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else {}

    def save_positions(self, positions: dict[str, str]) -> Path:
        return _write(self.home / "positions.json", json.dumps(positions, indent=2, sort_keys=True))

    def load_settings(self) -> Settings:
        path = self.home / "settings.json"
        return Settings.model_validate_json(path.read_text("utf-8")) if path.exists() else Settings()

    def save_settings(self, settings: Settings) -> Path:
        return _write(self.home / "settings.json", settings.model_dump_json(indent=2))

    def load_api_key(self) -> str | None:
        """Claude API key entered in the GUI; kept out of settings.json so that can be shared."""
        path = self.home / "api_key"
        return (path.read_text("utf-8").strip() or None) if path.exists() else None

    def save_api_key(self, key: str | None) -> None:
        if key:
            _write(self.home / "api_key", key.strip())
        else:
            (self.home / "api_key").unlink(missing_ok=True)

    def load_keyboard(self) -> KeyboardKnob:
        path = self.home / "keyboard.json"
        return KeyboardKnob.model_validate_json(path.read_text("utf-8")) if path.exists() else KeyboardKnob()

    def save_keyboard(self, knob: KeyboardKnob) -> Path:
        return _write(self.home / "keyboard.json", knob.model_dump_json(indent=2))

    def load_mobiflight(self) -> MobiFlightImport | None:
        path = self.home / "mobiflight.json"
        return MobiFlightImport.model_validate_json(path.read_text("utf-8")) if path.exists() else None

    def save_mobiflight(self, imported: MobiFlightImport) -> Path:
        return _write(self.home / "mobiflight.json", imported.model_dump_json(indent=2))

    def clear_mobiflight(self) -> None:
        (self.home / "mobiflight.json").unlink(missing_ok=True)

    def load_mapping(self, aircraft_key: str, fingerprint: str) -> MappingProfile | None:
        path = self._mapping_path(aircraft_key, fingerprint)
        return MappingProfile.model_validate_json(path.read_text("utf-8")) if path.exists() else None

    def save_mapping(self, mapping: MappingProfile) -> Path:
        path = self._mapping_path(mapping.aircraft_key, mapping.setup_fingerprint)
        return _write(path, mapping.model_dump_json(indent=2))

    def load_aircraft(self, aircraft_key: str) -> AircraftProfile | None:
        path = self._aircraft_path(aircraft_key)
        return AircraftProfile.model_validate_json(path.read_text("utf-8")) if path.exists() else None

    def save_aircraft(self, profile: AircraftProfile) -> Path:
        return _write(self._aircraft_path(profile.aircraft.key), profile.model_dump_json(indent=2))


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, "utf-8")
    tmp.replace(path)
    return path
