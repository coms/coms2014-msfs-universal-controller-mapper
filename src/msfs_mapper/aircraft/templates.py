"""Pick a checklist template for an aircraft and build its function priority list offline."""

from __future__ import annotations

from functools import cache

from msfs_mapper.data import function_catalog, list_yaml
from msfs_mapper.models import AircraftInfo, AircraftProfile, Checklist

# SimConnect ENGINE TYPE values
PISTON, JET, TURBOPROP = 0, 1, 5


@cache
def templates() -> dict[str, dict]:
    return {raw["id"]: raw for raw in list_yaml("checklists")}


def choose_template(aircraft: AircraftInfo) -> str:
    if aircraft.category.strip().casefold() == "helicopter":
        return "helicopter"
    if aircraft.engine_type == JET:
        return "jet_twin"
    if aircraft.engine_type == TURBOPROP:
        return "turboprop"
    return "piston_single"


def profile_from_template(aircraft: AircraftInfo, template_id: str | None = None) -> AircraftProfile:
    template_id = template_id or choose_template(aircraft)
    raw = templates()[template_id]
    functions = [f for f in raw["functions"] if _applies(f, aircraft)]
    return AircraftProfile(
        aircraft=aircraft,
        template=template_id,
        functions=functions,
        checklists=[Checklist.model_validate(c) for c in raw.get("checklists", [])],
    )


def _applies(function_id: str, aircraft: AircraftInfo) -> bool:
    if function_id not in function_catalog():
        return False
    if function_id == "gear":
        return aircraft.retractable_gear
    if function_id in {"throttle_1", "throttle_2"}:
        return aircraft.engine_count >= 2
    if function_id == "throttle_3":
        return aircraft.engine_count >= 3
    if function_id == "throttle_4":
        return aircraft.engine_count >= 4
    if function_id == "reversers":
        return aircraft.engine_type in {JET, TURBOPROP}
    if function_id == "throttle":
        # Twins get split levers; keep the combined throttle only as a fallback for singles.
        return aircraft.engine_count < 2
    return True
