"""Enumerate game controllers on USB and join them with the device catalog."""

from __future__ import annotations

from typing import Protocol

from msfs_mapper.devices.catalog import DeviceCatalog
from msfs_mapper.models import ControllerSetup, DetectedDevice, SetupDevice


def parse_sdl_guid(guid: str) -> tuple[int | None, int | None]:
    """Extract USB vendor and product ids from an SDL2 joystick GUID.

    SDL2 GUID layout (16 bytes, little-endian words): bus, crc, vendor, 0, product, 0, version, ...
    GUIDs from drivers that do not expose USB ids have a zero vendor word.
    """
    if len(guid) != 32:
        return None, None
    try:
        raw = bytes.fromhex(guid)
    except ValueError:
        return None, None
    vendor = int.from_bytes(raw[4:6], "little")
    product = int.from_bytes(raw[8:10], "little")
    if vendor == 0:
        return None, None
    return vendor, product


class DeviceBackend(Protocol):
    def list_devices(self) -> list[DetectedDevice]: ...


class PygameBackend:
    """Reads controllers through SDL2 (pygame), the same layer most sim tools use on Windows."""

    def __init__(self) -> None:
        import pygame  # optional dependency: pip install msfs-mapper[sim]

        self._pygame = pygame
        pygame.joystick.init()

    def list_devices(self) -> list[DetectedDevice]:
        devices = []
        for index in range(self._pygame.joystick.get_count()):
            joy = self._pygame.joystick.Joystick(index)
            guid = joy.get_guid()
            vendor, product = parse_sdl_guid(guid)
            devices.append(
                DetectedDevice(
                    index=index,
                    name=joy.get_name(),
                    vendor_id=vendor,
                    product_id=product,
                    num_axes=joy.get_numaxes(),
                    num_buttons=joy.get_numbuttons(),
                    num_hats=joy.get_numhats(),
                    guid=guid,
                )
            )
        return devices


def build_setup(detected: list[DetectedDevice], catalog: DeviceCatalog) -> ControllerSetup:
    devices = []
    for device in detected:
        definition = catalog.lookup(device.usb_id)
        position = definition.default_position if definition else "center"
        devices.append(SetupDevice(detected=device, definition=definition, position=position))
    return ControllerSetup(devices=devices)
