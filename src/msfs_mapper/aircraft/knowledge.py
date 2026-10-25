"""Ask Claude to tailor the template to a specific aircraft (variant quirks, add-on controls)."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from msfs_mapper.ai import Claude
from msfs_mapper.aircraft.templates import profile_from_template, templates
from msfs_mapper.data import function_catalog
from msfs_mapper.models import AircraftInfo, AircraftProfile, Checklist, SimFunction


class AircraftAdvice(BaseModel):
    template: str = Field(description="Best matching template id")
    functions: list[str] = Field(
        description="Function ids this aircraft needs, highest priority first; axis functions in "
        "cockpit order left to right. Use catalog ids or ids of custom_functions."
    )
    checklists: list[Checklist] = Field(description="Before takeoff, takeoff, approach and landing flows")
    custom_functions: list[SimFunction] = Field(
        description="Only for controls this aircraft does not drive via standard SimConnect events "
        "(e.g. add-on L:var or H:event controls as calculator code). Empty if none are needed."
    )
    notes: str = Field(description="Mapping caveats a pilot should know, e.g. 'Fenix A320 needs ...'")


SYSTEM = """You are an airline and general-aviation training captain who also knows Microsoft
Flight Simulator add-ons in depth. Given a loaded aircraft, decide which cockpit functions a pilot
needs on physical controls to fly the takeoff and landing checklists without touching the mouse.
Prefer functions from the provided catalog. Add a custom function only when you are confident this
specific aircraft ignores the standard event, and give its calculator code exactly. Never invent
SimConnect event names."""


def advise(claude: Claude, aircraft: AircraftInfo) -> AircraftProfile:
    """Build an AircraftProfile with Claude, validated against the catalog."""
    catalog = function_catalog()
    baseline = profile_from_template(aircraft)
    prompt = {
        "aircraft": aircraft.model_dump(mode="json"),
        "templates": {tid: t["description"] for tid, t in templates().items()},
        "baseline_profile": baseline.functions,
        "catalog": {fid: {"name": f.name, "kinds": [k.value for k in f.preferred_kinds]} for fid, f in catalog.items()},
    }
    advice = claude.structured(
        system=SYSTEM,
        content=[{"type": "text", "text": json.dumps(prompt, indent=1)}],
        output=AircraftAdvice,
    )
    custom = {f.id: f for f in advice.custom_functions if f.id not in catalog}
    known = catalog.keys() | custom.keys()
    functions = list(dict.fromkeys(f for f in advice.functions if f in known))
    if not functions:
        return baseline
    return AircraftProfile(
        aircraft=aircraft,
        template=advice.template if advice.template in templates() else baseline.template,
        functions=functions,
        checklists=advice.checklists or baseline.checklists,
        custom_functions=list(custom.values()),
        notes=advice.notes,
    )
