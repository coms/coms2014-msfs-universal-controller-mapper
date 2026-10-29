"""Let Claude improve the heuristic mapping, then validate every binding it proposes."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from msfs_mapper.ai import Claude
from msfs_mapper.mapping.engine import MOMENTARY, free_slots, functions_for, heuristic_map, is_compatible
from msfs_mapper.models import (
    AircraftProfile,
    Binding,
    ControllerSetup,
    MappingProfile,
    MobiFlightImport,
)


class ProposedBinding(BaseModel):
    device: str
    control: str
    function: str
    invert: bool = False
    reason: str = Field(description="One short sentence on why this control suits this function")


class ProposedMapping(BaseModel):
    bindings: list[ProposedBinding]


SYSTEM = """You map a pilot's physical flight-sim controls to aircraft functions.
Goals, in order: every function used in the takeoff and landing checklists gets a control;
the control's physical shape and label match the function (a gear lever drives the gear, a
two-position toggle drives lights, a rotary knob drives a selector); levers keep the real
cockpit order left to right; controls the pilot reaches without looking (yoke buttons) get the
time-critical functions (autopilot disconnect, trim). A control can drive one function only and
only through a kind of action listed for that function. Functions listed as handled by
MobiFlight are already on the pilot's MobiFlight panels: do not map them again, except those
listed as shareable, which may also go on a button, encoder or hat. Return the full mapping."""


def ai_map(
    claude: Claude,
    setup: ControllerSetup,
    profile: AircraftProfile,
    previous: MappingProfile | None = None,
    external: MobiFlightImport | None = None,
) -> MappingProfile:
    baseline = heuristic_map(setup, profile, previous, external)
    functions = functions_for(profile)
    request = {
        "aircraft": profile.aircraft.model_dump(mode="json"),
        "aircraft_notes": profile.notes,
        "checklists": [c.model_dump(mode="json") for c in profile.checklists],
        "functions_by_priority": [
            {"id": fid, "name": functions[fid].name,
             "actions": [k for k, v in functions[fid].actions if v is not None]}
            for fid in profile.functions if fid in functions
        ],
        "devices": [
            {"device": d.key, "name": d.detected.name, "position": d.position,
             "controls": [c.model_dump(mode="json", include={"id", "kind", "label", "roles"}) for c in d.controls]}
            for d in setup.devices
        ],
        "baseline_mapping": [b.model_dump(mode="json", include={"device", "control", "function"}) for b in baseline.bindings],
        "locked": [b.model_dump(mode="json") for b in baseline.bindings if b.locked],
        "handled_by_mobiflight": [
            {"function": b.function, "panel": b.module, "input": b.input} for b in baseline.external
        ],
        "shareable_with_mobiflight": sorted(external.shared_functions()) if external else [],
    }
    proposal = claude.structured(
        system=SYSTEM,
        content=[{"type": "text", "text": json.dumps(request, indent=1)}],
        output=ProposedMapping,
    )
    return merge(setup, profile, baseline, proposal, external)


def merge(
    setup: ControllerSetup,
    profile: AircraftProfile,
    baseline: MappingProfile,
    proposal: ProposedMapping,
    external: MobiFlightImport | None = None,
) -> MappingProfile:
    """Accept valid AI bindings, keep locked ones, and back-fill the rest from the baseline."""
    functions = functions_for(profile)
    by_slot = {(s.device.key, s.control.id): s for s in free_slots(setup, external)}
    bindings = [b for b in baseline.bindings if b.locked]
    used_controls = {(b.device, b.control) for b in bindings}
    exclusive = external.exclusive_functions() if external else set()
    shared = external.shared_functions() if external else set()
    used_functions = {b.function for b in bindings} | exclusive

    def accept(binding: Binding) -> bool:
        slot = by_slot.get((binding.device, binding.control))
        function = functions.get(binding.function)
        if (
            slot is None or function is None
            or (binding.device, binding.control) in used_controls
            or binding.function in used_functions
            or not is_compatible(function, slot.control)
            or (binding.function in shared and slot.control.kind not in MOMENTARY)
        ):
            return False
        bindings.append(binding)
        used_controls.add((binding.device, binding.control))
        used_functions.add(binding.function)
        return True

    accepted_ai = sum(accept(Binding(**p.model_dump())) for p in proposal.bindings)
    for binding in baseline.bindings:
        if not binding.locked:
            accept(binding)

    order = {fid: i for i, fid in enumerate(profile.functions)}
    bindings.sort(key=lambda b: order.get(b.function, len(order)))
    return MappingProfile(
        aircraft_key=baseline.aircraft_key,
        setup_fingerprint=baseline.setup_fingerprint,
        bindings=bindings,
        unassigned_functions=[
            f for f in profile.functions if f in functions and f not in used_functions | shared
        ],
        external=baseline.external,
        external_shared=baseline.external_shared,
        source="ai" if accepted_ai else "heuristic",
    )
