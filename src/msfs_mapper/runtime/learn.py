"""Interactive wizard that confirms a device's HID indices by asking the user to move each control."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from msfs_mapper.models import ControlKind, DeviceDefinition, PhysicalControl
from msfs_mapper.runtime.inputs import AxisMoved, ButtonChanged, HatMoved, InputEvent

AXIS_TRAVEL = 0.5  # how far an axis must move from where it started to count

EventStream = Callable[[float], Iterator[InputEvent]]


def _first(events: Iterator[InputEvent], device: int, want: type) -> InputEvent | None:
    start: dict[int, float] = {}
    for event in events:
        if event.device != device or not isinstance(event, want):
            continue
        if isinstance(event, ButtonChanged) and not event.pressed:
            continue
        if isinstance(event, AxisMoved):
            origin = start.setdefault(event.axis, event.value)
            if abs(event.value - origin) < AXIS_TRAVEL:
                continue
        return event
    return None


def learn_device(
    definition: DeviceDefinition,
    device_index: int,
    stream: EventStream,
    prompt: Callable[[str], None] = print,
    timeout: float = 10.0,
) -> DeviceDefinition:
    """Walk through every control; unchanged (and unverified) if the user does nothing in time."""
    learned: list[PhysicalControl] = []
    for control in definition.controls:
        update: dict = {}

        def ask(text: str, want: type) -> InputEvent | None:
            prompt(f"[{control.label or control.id}] {text} (skip: wait {timeout:.0f}s)")
            return _first(stream(timeout), device_index, want)

        match control.kind:
            case ControlKind.AXIS:
                if ev := ask("move it through its full range", AxisMoved):
                    update = {"axis": ev.axis}
            case ControlKind.BUTTON:
                if ev := ask("press it", ButtonChanged):
                    update = {"button": ev.button}
            case ControlKind.SWITCH:
                if ev := ask("flip it to ON / DOWN", ButtonChanged):
                    update = {"on_button": ev.button}
                    off = ask("flip it to OFF / UP", ButtonChanged)
                    update["off_button"] = off.button if off and off.button != ev.button else None
            case ControlKind.ENCODER:
                inc = ask("turn / push it one step clockwise or up", ButtonChanged)
                dec = ask("turn / push it one step counter-clockwise or down", ButtonChanged)
                if inc and dec:
                    update = {"inc_button": inc.button, "dec_button": dec.button}
            case ControlKind.HAT:
                if ev := ask("push the hat in any direction", HatMoved):
                    update = {"hat": ev.hat}
        if update:
            update["verified"] = True
        learned.append(control.model_copy(update=update))
    return definition.model_copy(update={"controls": learned})
