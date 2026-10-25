"""Controller input events and the SDL (pygame) source that produces them."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class AxisMoved:
    device: int  # SDL joystick index
    axis: int
    value: float  # -1.0 .. 1.0


@dataclass(frozen=True)
class ButtonChanged:
    device: int
    button: int
    pressed: bool


@dataclass(frozen=True)
class HatMoved:
    device: int
    hat: int
    x: int
    y: int


InputEvent = AxisMoved | ButtonChanged | HatMoved


class PygameInputSource:
    def __init__(self) -> None:
        import pygame  # optional dependency: pip install msfs-mapper[sim]

        self._pygame = pygame
        pygame.init()
        pygame.joystick.init()
        self._joysticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
        # Events carry instance ids, mappings use enumeration indices.
        self._index = {joy.get_instance_id(): i for i, joy in enumerate(self._joysticks)}

    def events(self, timeout: float | None = None) -> Iterator[InputEvent]:
        """Yield input events; stops after `timeout` seconds without one (None = forever)."""
        pg = self._pygame
        while True:
            raw = pg.event.wait(int(timeout * 1000) if timeout else 0)
            if raw.type == pg.NOEVENT:
                return
            device = self._index.get(getattr(raw, "instance_id", None))
            if device is None:
                continue
            if raw.type == pg.JOYAXISMOTION:
                yield AxisMoved(device, raw.axis, raw.value)
            elif raw.type in (pg.JOYBUTTONDOWN, pg.JOYBUTTONUP):
                yield ButtonChanged(device, raw.button, raw.type == pg.JOYBUTTONDOWN)
            elif raw.type == pg.JOYHATMOTION:
                yield HatMoved(device, raw.hat, *raw.value)
