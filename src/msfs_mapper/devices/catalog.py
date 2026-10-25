"""Known controller models, keyed by USB vendor/product id."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from msfs_mapper.data import list_yaml
from msfs_mapper.models import DeviceDefinition


@cache
def builtin_definitions() -> tuple[DeviceDefinition, ...]:
    return tuple(DeviceDefinition.model_validate(raw) for raw in list_yaml("devices"))


class DeviceCatalog:
    """Built-in definitions overlaid with user definitions (learned or AI-drafted)."""

    def __init__(self, user_dir: Path | None = None):
        self.user_dir = user_dir
        self._by_usb: dict[str, DeviceDefinition] = {d.usb_id: d for d in builtin_definitions()}
        if user_dir and user_dir.is_dir():
            for path in sorted(user_dir.glob("*.json")):
                definition = DeviceDefinition.model_validate_json(path.read_text("utf-8"))
                self._by_usb[definition.usb_id] = definition

    def lookup(self, usb_id: str | None) -> DeviceDefinition | None:
        return self._by_usb.get(usb_id) if usb_id else None

    def save(self, definition: DeviceDefinition) -> Path:
        """Persist a user definition so it overrides the built-in one from now on."""
        if self.user_dir is None:
            raise ValueError("catalog has no user directory to save into")
        self.user_dir.mkdir(parents=True, exist_ok=True)
        path = self.user_dir / f"{definition.usb_id.replace(':', '_')}.json"
        path.write_text(json.dumps(definition.model_dump(mode="json"), indent=2), "utf-8")
        self._by_usb[definition.usb_id] = definition
        return path
