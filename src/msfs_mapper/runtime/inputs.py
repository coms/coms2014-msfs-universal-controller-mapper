"""Controller input events and the SDL (pygame) source that produces them."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import logging


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

log = logging.getLogger(__name__)


def parse_mobiflight_line(line: str, device: int, button_count: int, encoder_count: int) -> InputEvent | None:
    """Decode one line from the companion MobiFlight Mega sketch."""
    parts = line.strip().split(",")
    try:
        if len(parts) == 3 and parts[0] == "B":
            button, pressed = int(parts[1]), int(parts[2])
            if 0 <= button < button_count and pressed in (0, 1):
                return ButtonChanged(device, button, bool(pressed))
        elif len(parts) == 3 and parts[0] == "E":
            encoder, direction = int(parts[1]), int(parts[2])
            if 0 <= encoder < encoder_count and direction in (-1, 1):
                # Encoder buttons follow the regular button indices, inc then dec.
                button = button_count + encoder * 2 + (0 if direction > 0 else 1)
                return ButtonChanged(device, button, True)
    except ValueError:
        pass
    if line.strip() and not line.startswith("READY,"):
        log.warning("ignoring malformed MobiFlight serial event: %r", line.rstrip())
    return None


class MobiFlightSerialInputSource:
    """Reads button/encoder events from the companion custom Mega firmware."""

    def __init__(
        self,
        port: str,
        device: int,
        button_count: int = 8,
        encoder_count: int = 2,
        baudrate: int = 115200,
        serial_connection=None,
    ):
        if not 0 <= button_count <= 32 or not 0 <= encoder_count <= 3:
            raise ValueError("MobiFlight Mega supports 0-32 buttons and 0-3 encoders")
        if serial_connection is None:
            import serial  # optional dependency: pip install msfs-mapper[sim]

            serial_connection = serial.Serial(port, baudrate=baudrate, timeout=0)
        self._serial = serial_connection
        self._device = device
        self._button_count = button_count
        self._encoder_count = encoder_count
        self._buffer = bytearray()
        self._ready = False

    def events(self, timeout: float | None = None) -> Iterator[InputEvent]:
        import time

        deadline = time.monotonic() + timeout if timeout is not None else None
        while deadline is None or time.monotonic() <= deadline:
            chunk = self._serial.read(256)
            if chunk:
                self._buffer.extend(chunk)
                while b"\n" in self._buffer:
                    raw, _, remaining = self._buffer.partition(b"\n")
                    self._buffer = bytearray(remaining)
                    try:
                        line = raw.decode("ascii")
                    except UnicodeDecodeError:
                        log.warning("ignoring non-ASCII MobiFlight serial input")
                        continue
                    if line.startswith("READY,"):
                        self._accept_handshake(line)
                        continue
                    if not self._ready:
                        log.warning("ignoring MobiFlight input received before firmware handshake")
                        continue
                    event = parse_mobiflight_line(
                        line, self._device, self._button_count, self._encoder_count
                    )
                    if event is not None:
                        yield event
            elif deadline is not None:
                return
            if timeout == 0:
                return

    def _accept_handshake(self, line: str) -> None:
        try:
            _, version, buttons, encoders = line.strip().split(",")
            actual = (int(version), int(buttons), int(encoders))
        except ValueError as exc:
            raise ValueError(f"invalid MobiFlight firmware handshake: {line.rstrip()}") from exc
        expected = (1, self._button_count, self._encoder_count)
        if actual != expected:
            raise ValueError(
                "MobiFlight firmware mismatch: expected protocol/buttons/encoders "
                f"{expected}, got {actual}"
            )
        self._ready = True

    def close(self) -> None:
        self._serial.close()


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
