"""Import MobiFlight Connector projects (.mcc) so existing MobiFlight inputs are respected.

MobiFlight boards are Arduinos on a serial port, so SDL never sees them. Their inputs and what
each one does are recorded in the .mcc project instead:

    <MobiflightConnector><inputs>
      <config guid="..."><active>true</active><description>Gear</description>
        <settings serial="Cockpit Mega/ SN-123" name="Gear switch" type="Button">
          <button><onPress type="MSFS2020CustomInputAction" command="(&gt;K:GEAR_DOWN)"/>...

The parser is deliberately tolerant: it reads attributes or child elements, ignores unknown
tags, and treats any element carrying a `command`/`eventId`-style attribute as an action, so
small format differences between MobiFlight versions don't break the import.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from msfs_mapper.ai import Claude
from msfs_mapper.models import ControllerSetup, ExternalBinding, MobiFlightImport, SimFunction

K_EVENT = re.compile(r">\s*K:(?:\d+:)?([A-Za-z0-9_]+)")
BARE_EVENT = re.compile(r"^[A-Z][A-Z0-9_]+$")
ACTION_ATTRS = ("command", "eventId", "event", "inputValue", "value")
JOYSTICK_BUTTON = re.compile(r"button\s*(\d+)", re.IGNORECASE)


class MobiFlightError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _field(element: ET.Element, name: str) -> str:
    """Read `name` as an attribute or a direct child element (MobiFlight has used both)."""
    if name in element.attrib:
        return element.attrib[name].strip()
    for child in element:
        if _local(child.tag).lower() == name.lower():
            return (child.text or "").strip()
    return ""


def _module_name(serial: str) -> str:
    # "Cockpit Mega/ SN-3c1-c2a" -> "Cockpit Mega"; "Bravo Throttle Quadrant / JS-{guid}" -> ...
    return serial.split("/", 1)[0].strip() or serial


def _actions(settings: ET.Element) -> list[str]:
    commands = []
    for element in settings.iter():
        values = [element.attrib[a] for a in ACTION_ATTRS if element.attrib.get(a, "").strip()]
        action_type = element.attrib.get("type", "")
        if values and (action_type.endswith("Action") or "command" in element.attrib):
            commands.extend(v.strip() for v in values)
    return commands


def _maintained(settings: ET.Element, input_type: str) -> bool:
    """Analog inputs and buttons that also act on release are switches/levers, not buttons."""
    kind = input_type.lower()
    if "analog" in kind:
        return True
    if "encoder" in kind:
        return False
    return any(
        _local(e.tag).lower() == "onrelease" and _actions(e)
        for e in settings.iter()
    )


def parse_project(source: Path | str) -> list[ExternalBinding]:
    """Parse a .mcc file (path) or its XML text into one ExternalBinding per active input."""
    try:
        root = ET.parse(source).getroot() if isinstance(source, Path) else ET.fromstring(source)
    except ET.ParseError as exc:
        raise MobiFlightError(f"not a MobiFlight project (invalid XML): {exc}") from exc
    inputs = [e for e in root.iter() if _local(e.tag).lower() == "inputs"]
    if not inputs:
        raise MobiFlightError("no <inputs> section found; is this a MobiFlight .mcc project?")

    bindings = []
    for config in (c for section in inputs for c in section if _local(c.tag) == "config"):
        if _field(config, "active").lower() == "false":
            continue
        settings = next((c for c in config if _local(c.tag) == "settings"), None)
        if settings is None:
            continue
        serial = _field(settings, "serial")
        input_type = _field(settings, "type")
        bindings.append(
            ExternalBinding(
                module=_module_name(serial),
                serial=serial,
                input=_field(settings, "name"),
                input_type=input_type,
                maintained=_maintained(settings, input_type),
                description=_field(config, "description"),
                commands=_actions(settings),
            )
        )
    return bindings


def event_index(functions: dict[str, SimFunction]) -> dict[str, str]:
    """SimConnect event name or calculator code -> function id."""
    index: dict[str, str] = {}
    for function in functions.values():
        for _, action in function.actions:
            if action is not None:
                index.setdefault(action.value.strip(), function.id)
    return index


def recognise(bindings: list[ExternalBinding], functions: dict[str, SimFunction]) -> list[ExternalBinding]:
    """Fill in `function` where an input's commands clearly drive a catalog function."""
    index = event_index(functions)
    result = []
    for binding in bindings:
        votes: Counter[str] = Counter()
        for command in binding.commands:
            if command in index:  # exact calculator code or bare event name
                votes[index[command]] += 1
                continue
            names = K_EVENT.findall(command) or ([command] if BARE_EVENT.match(command) else [])
            votes.update(index[n] for n in names if n in index)
        function = votes.most_common(1)[0][0] if votes else None
        result.append(binding.model_copy(update={"function": function}))
    return result


def attach_joysticks(bindings: list[ExternalBinding], setup: ControllerSetup) -> list[ExternalBinding]:
    """Link MobiFlight joystick inputs (serial contains 'JS-') to devices we also read.

    MobiFlight names joystick buttons 'Button 1', 'Button 2', ... (1-based); SDL is 0-based.
    """
    names = {d.detected.name.lower(): d.key for d in setup.devices}
    result = []
    for binding in bindings:
        update = {}
        key = names.get(binding.module.lower())
        if "JS-" in binding.serial and key:
            update["usb_device"] = key
            if match := JOYSTICK_BUTTON.search(binding.input):
                update["button"] = int(match.group(1)) - 1
        result.append(binding.model_copy(update=update))
    return result


def import_project(
    path: Path, functions: dict[str, SimFunction], setup: ControllerSetup | None = None
) -> MobiFlightImport:
    bindings = recognise(parse_project(path), functions)
    if setup is not None:
        bindings = attach_joysticks(bindings, setup)
    return MobiFlightImport(project=str(path), bindings=bindings)


class Identified(BaseModel):
    index: int
    function: str | None = Field(description="Catalog function id, or null if none fits")


class Identification(BaseModel):
    inputs: list[Identified]


IDENTIFY_SYSTEM = """You read MobiFlight input configurations for Microsoft Flight Simulator and
say which cockpit function each one operates. Commands are MobiFlight presets or RPN calculator
code (K: events, H: events, L: variables of add-on aircraft). Answer with a catalog function id
only when the input clearly operates that function; otherwise null."""


def ai_identify(
    claude: Claude, imported: MobiFlightImport, functions: dict[str, SimFunction]
) -> MobiFlightImport:
    """Ask Claude about inputs the event table could not recognise (add-on L:vars, presets)."""
    unknown = [(i, b) for i, b in enumerate(imported.bindings) if b.function is None and b.commands]
    if not unknown:
        return imported
    request = {
        "catalog": {fid: f.name for fid, f in functions.items()},
        "inputs": [
            {"index": i, "name": b.input, "description": b.description, "type": b.input_type,
             "commands": b.commands}
            for i, b in unknown
        ],
    }
    answer = claude.structured(
        system=IDENTIFY_SYSTEM,
        content=[{"type": "text", "text": json.dumps(request, indent=1)}],
        output=Identification,
        effort="medium",
    )
    bindings = list(imported.bindings)
    asked = {i for i, _ in unknown}
    for item in answer.inputs:
        if item.index in asked and item.function in functions:
            bindings[item.index] = bindings[item.index].model_copy(update={"function": item.function})
    return imported.model_copy(update={"bindings": bindings})
