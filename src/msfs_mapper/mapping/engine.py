"""Deterministic mapper: scores every (function, control) pair and assigns greedily by priority.

It works offline and gives the AI pass a sane baseline to improve on, and is also the
validator for whatever the AI proposes (see `is_compatible`).
"""

from __future__ import annotations

from dataclasses import dataclass

from msfs_mapper.data import function_catalog
from msfs_mapper.models import (
    AircraftProfile,
    Binding,
    ControlKind,
    ControllerSetup,
    MappingProfile,
    MobiFlightImport,
    PhysicalControl,
    SetupDevice,
    SimFunction,
)

# Roles that only say what *kind* of thing a control is, not what it is for.
GENERIC_ROLES = {"lever", "switch", "encoder", "lights", "autopilot", "trim", "yoke.button"}
# Controls that hold no position, so a second one for the same function can't disagree with it.
MOMENTARY = {ControlKind.BUTTON, ControlKind.ENCODER, ControlKind.HAT}


@dataclass(frozen=True)
class Slot:
    device: SetupDevice
    control: PhysicalControl
    order: int  # position in the setup, used as a stable tie-break (keeps levers left-to-right)


def functions_for(profile: AircraftProfile) -> dict[str, SimFunction]:
    return {**function_catalog(), **{f.id: f for f in profile.custom_functions}}


def is_compatible(function: SimFunction, control: PhysicalControl) -> bool:
    return function.actions.supports(control.kind)


def score(function: SimFunction, control: PhysicalControl) -> int:
    """0 means 'do not assign'. Higher is a better fit."""
    if not is_compatible(function, control):
        return 0
    roles = set(control.roles)
    specific = (roles & set(function.roles)) - GENERIC_ROLES
    if function.roles and function.roles[0] in roles:
        role_score = 100
    elif specific:
        role_score = 60
    elif roles & set(function.roles):
        role_score = 20
    elif not roles:
        role_score = 5  # unlabelled control on an unknown device: usable, but last resort
    else:
        return 0  # control has a declared purpose that is not this one
    kinds = function.preferred_kinds
    kind_score = 30 - 10 * kinds.index(control.kind) if control.kind in kinds else 0
    return role_score + max(kind_score, 0)


def slots(setup: ControllerSetup) -> list[Slot]:
    return [
        Slot(device, control, order)
        for order, (device, control) in enumerate(
            (d, c) for d in setup.devices for c in d.controls
        )
    ]


def control_buttons(control: PhysicalControl) -> set[int]:
    buttons = {control.button, control.on_button, control.off_button, control.inc_button, control.dec_button}
    return buttons - {None}


def free_slots(setup: ControllerSetup, external: MobiFlightImport | None) -> list[Slot]:
    """All slots minus controls whose buttons MobiFlight already reads on the same joystick."""
    reserved = {
        (b.usb_device, b.button) for b in (external.bindings if external else [])
        if b.usb_device and b.button is not None
    }
    return [
        s for s in slots(setup)
        if not any((s.device.key, button) in reserved for button in control_buttons(s.control))
    ]


def heuristic_map(
    setup: ControllerSetup,
    profile: AircraftProfile,
    previous: MappingProfile | None = None,
    external: MobiFlightImport | None = None,
) -> MappingProfile:
    functions = functions_for(profile)
    available = free_slots(setup, external)
    bindings: list[Binding] = []
    # Functions MobiFlight already drives stay with MobiFlight, except momentary ones the user
    # allowed us to double up on our own momentary controls.
    done: set[str] = external.exclusive_functions() if external else set()
    shared = external.shared_functions() if external else set()

    # User-pinned bindings survive re-mapping as long as the hardware is still there.
    for binding in previous.bindings if previous else []:
        slot = _find(available, binding.device, binding.control)
        if binding.locked and slot and binding.function in functions:
            bindings.append(binding)
            available.remove(slot)
            done.add(binding.function)

    unassigned = []
    for function_id in profile.functions:
        if function_id in done or function_id not in functions:
            continue
        function = functions[function_id]
        pool = [s for s in available if s.control.kind in MOMENTARY] if function_id in shared else available
        best = max(pool, key=lambda s: (score(function, s.control), -s.order), default=None)
        if best is None or score(function, best.control) == 0:
            if function_id not in shared:  # shared ones still have their MobiFlight control
                unassigned.append(function_id)
            continue
        available.remove(best)
        done.add(function_id)
        bindings.append(
            Binding(
                device=best.device.key,
                control=best.control.id,
                function=function_id,
                reason=f"score {score(function, best.control)}: {best.control.label or best.control.id}",
            )
        )

    return MappingProfile(
        aircraft_key=profile.aircraft.key,
        setup_fingerprint=setup.fingerprint(),
        bindings=bindings,
        unassigned_functions=unassigned,
        external=[b for b in external.bindings if b.function] if external else [],
        external_shared=external.allow_shared if external else False,
        source="heuristic",
    )


def _find(available: list[Slot], device: str, control: str) -> Slot | None:
    return next((s for s in available if s.device.key == device and s.control.id == control), None)
