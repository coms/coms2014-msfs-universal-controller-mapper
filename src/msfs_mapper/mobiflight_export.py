"""Write the automatic mapping into a MobiFlight Connector project, so MobiFlight runs it.

MobiFlight reads USB game controllers as "joysticks" next to its own boards, and it can send
calculator code our bridge cannot. Exporting therefore hands every exportable binding to
MobiFlight: `msfs-mapper run` then skips those bindings so nothing is sent twice.

MobiFlight addresses a joystick by a serial like "Bravo Throttle Quadrant / JS-{instance id}".
That id is not derivable from what SDL reports, so it is learned from the imported project:
a device is exportable once MobiFlight has at least one input configured on it. Generated
configs carry GENERATED_TAG in their description; the importer ignores them and every export
replaces them, so exporting and re-importing never feed back into each other.

Format details below (joystick input names, axis value range) follow MobiFlight 9/10 projects
as best known and are not yet verified against MobiFlight itself.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from msfs_mapper.mobiflight import GENERATED_TAG
from msfs_mapper.models import (
    Binding,
    ControlKind,
    ControllerSetup,
    MappingProfile,
    MobiFlightImport,
    PhysicalControl,
    SetupDevice,
    SimAction,
    SimFunction,
)

MSDATA = "urn:schemas-microsoft-com:xml-msdata"
INSTANCE_TYPE = "MobiFlight.InputConfigItem, MFConnector"
ACTION_TYPE = "MSFS2020CustomInputAction"
# SDL axis index -> MobiFlight/DirectInput axis name (usual HID order: X, Y, Z, Rx, Ry, Rz, sliders).
AXIS_NAMES = ["X", "Y", "Z", "RotationX", "RotationY", "RotationZ", "Slider1", "Slider2"]
# MobiFlight joystick axes report 0..65535; SimConnect axis events take -16384..16383.
AXIS_SCALE = "@ 32768 - 2 /"
AXIS_SCALE_INVERTED = "32768 @ - 2 /"

ET.register_namespace("msdata", MSDATA)


@dataclass
class ExportResult:
    path: Path | None = None
    exported: list[Binding] = field(default_factory=list)
    # Devices MobiFlight has no input on yet, so their joystick id is unknown.
    needs_device_id: list[str] = field(default_factory=list)
    # Bindings MobiFlight can't take (keyboard knob, hats): msfs-mapper run keeps driving them.
    kept: list[Binding] = field(default_factory=list)


def joystick_serials(imported: MobiFlightImport | None) -> dict[str, str]:
    """Device name (lower case) -> MobiFlight joystick serial, learned from the import."""
    serials: dict[str, str] = {}
    for b in imported.bindings if imported else []:
        if "JS-" in b.serial:
            serials.setdefault(b.module.lower(), b.serial)
    return serials


def split(
    setup: ControllerSetup,
    mapping: MappingProfile,
    functions: dict[str, SimFunction],
    imported: MobiFlightImport | None,
) -> ExportResult:
    """Decide which bindings MobiFlight will run. Same answer for exporting and for `run`."""
    serials = joystick_serials(imported)
    devices = {d.key: d for d in setup.devices}
    result = ExportResult()
    missing: set[str] = set()
    for binding in mapping.bindings:
        device = devices.get(binding.device)
        control = _control(device, binding.control)
        function = functions.get(binding.function)
        if (
            device is None or control is None or function is None
            or device.detected.index < 0  # virtual devices (keyboard knob): MobiFlight can't see them
            or not _inputs(control, function, binding.invert)  # hats, calculator-code axes
        ):
            result.kept.append(binding)
        elif device.detected.name.lower() in serials:
            result.exported.append(binding)
        else:
            result.kept.append(binding)
            missing.add(device.detected.name)
    result.needs_device_id = sorted(missing)
    return result


def export_project(
    setup: ControllerSetup,
    mapping: MappingProfile,
    functions: dict[str, SimFunction],
    imported: MobiFlightImport | None,
    target: Path,
) -> ExportResult:
    result = split(setup, mapping, functions, imported)
    if not result.exported:
        return result
    root = _base_project(imported)
    inputs = next(e for e in root if e.tag == "inputs")
    for config in [c for c in inputs if GENERATED_TAG in (c.findtext("description") or "")]:
        inputs.remove(config)

    serials = joystick_serials(imported)
    devices = {d.key: d for d in setup.devices}
    for binding in result.exported:
        device = devices[binding.device]
        control = _control(device, binding.control)
        function = functions[binding.function]
        serial = serials[device.detected.name.lower()]
        for name, input_type, triggers in _inputs(control, function, binding.invert):
            inputs.append(_config(mapping, binding, function, serial, name, input_type, triggers))

    target.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tmp = target.with_suffix(".tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    tmp.replace(target)
    result.path = target
    return result


def export_path(folder: Path, imported: MobiFlightImport | None, aircraft_title: str) -> Path:
    base = Path(imported.project).stem if imported else "msfs-mapper"
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in aircraft_title).strip()
    return folder / f"{base} - {safe}.mcc"


# --------------------------------------------------------------------------- helpers


def _control(device: SetupDevice | None, control_id: str) -> PhysicalControl | None:
    return next((c for c in device.controls if c.id == control_id), None) if device else None


def _base_project(imported: MobiFlightImport | None) -> ET.Element:
    """The user's project (untouched apart from our configs), or an empty one."""
    if imported and Path(imported.project).is_file():
        try:
            root = ET.parse(imported.project).getroot()
            if root.find("inputs") is None:
                ET.SubElement(root, "inputs")
            return root
        except ET.ParseError:
            pass
    root = ET.Element("MobiflightConnector")
    ET.SubElement(root, "outputs")
    ET.SubElement(root, "inputs")
    return root


def _command(action: SimAction) -> str:
    return action.value if action.type == "calculator" else f"(>K:{action.value})"


def _button(index: int) -> str:
    return f"Button {index + 1}"  # MobiFlight numbers joystick buttons from 1


Trigger = tuple[str, str]  # (element name, command)


def _inputs(
    control: PhysicalControl, function: SimFunction, invert: bool
) -> list[tuple[str, str, list[Trigger]]]:
    """MobiFlight inputs for one control: (input name, input type, [(trigger, command)])."""
    a = function.actions
    match control.kind:
        case ControlKind.AXIS:
            if a.axis is None or a.axis.type != "event":
                return []
            scale = AXIS_SCALE_INVERTED if invert else AXIS_SCALE
            name = AXIS_NAMES[control.axis] if control.axis < len(AXIS_NAMES) else str(control.axis)
            return [(f"Axis {name}", "AnalogInput", [("onChange", f"{scale} (>K:{a.axis.value})")])]
        case ControlKind.BUTTON:
            return [(_button(control.button), "Button", [("onPress", _command(a.press))])]
        case ControlKind.ENCODER:
            return [
                (_button(control.inc_button), "Button", [("onPress", _command(a.inc))]),
                (_button(control.dec_button), "Button", [("onPress", _command(a.dec))]),
            ]
        case ControlKind.SWITCH:
            on, off = _command(a.on or a.press), _command(a.off or a.press)
            if control.off_button is None:  # single contact: release means OFF
                return [(_button(control.on_button), "Button", [("onPress", on), ("onRelease", off)])]
            return [
                (_button(control.on_button), "Button", [("onPress", on)]),
                (_button(control.off_button), "Button", [("onPress", off)]),
            ]
    return []


def _config(
    mapping: MappingProfile, binding: Binding, function: SimFunction,
    serial: str, name: str, input_type: str, triggers: list[Trigger],
) -> ET.Element:
    config = ET.Element("config", guid=str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"msfs-mapper:{mapping.aircraft_key}:{binding.device}:{name}")))
    ET.SubElement(config, "active").text = "true"
    ET.SubElement(config, "description").text = f"{GENERATED_TAG} {function.name}"
    settings = ET.SubElement(config, "settings", {
        f"{{{MSDATA}}}InstanceType": INSTANCE_TYPE, "serial": serial, "name": name, "type": input_type,
    })
    group = ET.SubElement(settings, "analog" if input_type == "AnalogInput" else "button")
    for trigger, command in triggers:
        ET.SubElement(group, trigger, type=ACTION_TYPE, command=command, presetId="")
    ET.SubElement(settings, "preconditions")
    ET.SubElement(settings, "configrefs")
    return config
