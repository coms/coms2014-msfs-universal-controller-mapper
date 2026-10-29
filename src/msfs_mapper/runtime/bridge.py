"""Route controller input through a MappingProfile to simulator actions."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Protocol

from msfs_mapper.models import (
    ControlKind,
    ControllerSetup,
    FunctionActions,
    MappingProfile,
    PhysicalControl,
    SimAction,
    SimFunction,
)
from msfs_mapper.runtime.inputs import AxisMoved, ButtonChanged, HatMoved, InputEvent

log = logging.getLogger(__name__)

SIM_AXIS_MAX = 16383  # SimConnect AXIS_*_SET events take -16383..16383
AXIS_DEADBAND = 0.002


class Executor(Protocol):
    def send(self, action: SimAction, value: int = 0) -> None: ...


class LogExecutor:
    """Dry run: records what would be sent."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, int]] = []

    def send(self, action: SimAction, value: int = 0) -> None:
        self.sent.append((action.value, value))
        log.info("would send %s %s", action.value, value)


class SimConnectExecutor:
    def __init__(self, sim: Any | None = None):
        if sim is None:
            from SimConnect import SimConnect  # optional dependency

            sim = SimConnect()
        from SimConnect import AircraftEvents

        self._events = AircraftEvents(sim)
        self._cache: dict[str, Any] = {}

    def send(self, action: SimAction, value: int = 0) -> None:
        if action.type == "calculator":
            # Needs the MobiFlight WASM module's calculator-code channel; not wired up yet.
            log.warning("calculator code not supported yet, skipped: %s", action.value)
            return
        event = self._cache.get(action.value)
        if event is None:
            event = self._events.find(action.value)
            if event is None:
                log.error("unknown SimConnect event %s", action.value)
                return
            self._cache[action.value] = event
        event(value)


class Router:
    """Precomputes lookup tables so each input event is a dict hit."""

    def __init__(
        self,
        setup: ControllerSetup,
        mapping: MappingProfile,
        functions: dict[str, SimFunction],
        executor: Executor,
    ):
        self.executor = executor
        self._axes: dict[tuple[int, int], tuple[SimAction, bool]] = {}
        self._buttons: dict[tuple[int, int, bool], SimAction] = {}
        self._hats: dict[tuple[int, int], tuple[SimAction, SimAction]] = {}
        self._last_axis: dict[tuple[int, int], float] = {}

        devices = {d.key: d for d in setup.devices}
        for binding in mapping.bindings:
            device = devices.get(binding.device)
            function = functions.get(binding.function)
            control = next((c for c in device.controls if c.id == binding.control), None) if device else None
            if device is None or function is None or control is None:
                log.warning("skipping stale binding %s/%s", binding.device, binding.control)
                continue
            self._register(device.detected.index, control, function.actions, binding.invert)

    def _register(
        self, index: int, control: PhysicalControl, actions: FunctionActions, invert: bool
    ) -> None:
        match control.kind:
            case ControlKind.AXIS:
                self._axes[(index, control.axis)] = (actions.axis, invert)
            case ControlKind.BUTTON:
                self._buttons[(index, control.button, True)] = actions.press
            case ControlKind.SWITCH:
                on = actions.on or actions.press
                off = actions.off or actions.press
                self._buttons[(index, control.on_button, True)] = on
                if control.off_button is not None:
                    self._buttons[(index, control.off_button, True)] = off
                else:  # single-contact switch: releasing the ON contact means OFF
                    self._buttons[(index, control.on_button, False)] = off
            case ControlKind.ENCODER:
                self._buttons[(index, control.inc_button, True)] = actions.inc
                self._buttons[(index, control.dec_button, True)] = actions.dec
            case ControlKind.HAT:
                self._hats[(index, control.hat)] = (actions.inc, actions.dec)

    def handles(self, device: int, button: int) -> bool:
        return (device, button, True) in self._buttons or (device, button, False) in self._buttons

    def handle(self, event: InputEvent) -> None:
        if isinstance(event, AxisMoved):
            key = (event.device, event.axis)
            target = self._axes.get(key)
            if target is None or abs(event.value - self._last_axis.get(key, 9.0)) < AXIS_DEADBAND:
                return
            self._last_axis[key] = event.value
            action, invert = target
            value = -event.value if invert else event.value
            self.executor.send(action, int(round(value * SIM_AXIS_MAX)))
        elif isinstance(event, ButtonChanged):
            action = self._buttons.get((event.device, event.button, event.pressed))
            if action is not None:
                self.executor.send(action)
        elif isinstance(event, HatMoved):
            target = self._hats.get((event.device, event.hat))
            if target is not None and event.y:
                self.executor.send(target[0] if event.y > 0 else target[1])

    def run(self, events: Iterable[InputEvent]) -> None:
        for event in events:
            self.handle(event)
