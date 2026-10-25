"""Use a photo of the cockpit setup to place devices and draft unknown device layouts."""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path

from pydantic import BaseModel, Field

from msfs_mapper.ai import Claude, image_block
from msfs_mapper.models import ControllerSetup, DetectedDevice, DeviceDefinition, PhysicalControl

POSITIONS = ["left", "center", "right", "floor", "overhead"]


class SeenDevice(BaseModel):
    manufacturer: str = Field(description="Brand if identifiable, else empty")
    model: str = Field(description="Product name, e.g. 'Bravo Throttle Quadrant'")
    position: str = Field(description=f"Relative to the pilot seat, one of {POSITIONS}")
    visible_labels: list[str] = Field(description="Printed labels or stickers readable on the device")
    usb_name: str = Field(description="The USB device name from the provided list this matches, or empty")


class SetupPhoto(BaseModel):
    devices: list[SeenDevice]
    notes: str = Field(description="Anything that affects mapping, e.g. labels the user added")


LAYOUT_SYSTEM = """You identify flight simulator hardware in photos of a home cockpit.
For every controller you can see, name it, say where it sits relative to the pilot seat and
transcribe readable labels. Match each one to a USB device name from the list you are given
when the match is clear; leave usb_name empty when unsure rather than guessing."""


def analyse_setup_photo(claude: Claude, photo: Path, detected: list[DetectedDevice]) -> SetupPhoto:
    usb_list = "\n".join(
        f"- {d.name} (USB {d.usb_id or 'unknown'}, {d.num_axes} axes, {d.num_buttons} buttons)"
        for d in detected
    )
    return claude.structured(
        system=LAYOUT_SYSTEM,
        content=[
            image_block(photo),
            {"type": "text", "text": f"USB game controllers currently connected:\n{usb_list}"},
        ],
        output=SetupPhoto,
        effort="medium",
    )


def apply_photo(setup: ControllerSetup, photo: SetupPhoto) -> list[SeenDevice]:
    """Copy positions from the photo onto the setup. Returns photo devices that matched nothing."""
    unmatched = []
    remaining = list(setup.devices)
    for seen in photo.devices:
        best, best_score = None, 0.0
        for device in remaining:
            names = [device.detected.name] + ([device.definition.name] if device.definition else [])
            score = max(
                1.0 if seen.usb_name and seen.usb_name == device.detected.name else
                SequenceMatcher(None, f"{seen.manufacturer} {seen.model}".lower(), n.lower()).ratio()
                for n in names
            )
            if score > best_score:
                best, best_score = device, score
        if best is not None and best_score >= 0.5:
            if seen.position in POSITIONS:
                best.position = seen.position
            remaining.remove(best)
        else:
            unmatched.append(seen)
    return unmatched


class DraftControls(BaseModel):
    controls: list[PhysicalControl]


DRAFT_SYSTEM = """You draft control layouts for flight simulator controllers that are not in the
catalog. Use your knowledge of the product and the photo to list its axes, buttons, toggle
switches, rotary encoders and hats with their likely 0-based SDL indices and semantic roles.
Only use indices below the reported axis/button/hat counts. Mark every control verified=false;
the user confirms them later with an interactive learn step."""

ROLE_HINT = (
    "Use roles from this vocabulary where they apply: yoke.roll yoke.pitch stick.roll stick.pitch "
    "stick.twist rudder brake.left brake.right throttle lever propeller mixture condition "
    "spoilers flaps gear trim.pitch autopilot.master autopilot.hdg autopilot.nav autopilot.apr "
    "autopilot.alt autopilot.vs autopilot.disconnect encoder.hdg encoder.alt encoder.vs "
    "lights.landing lights.taxi lights.nav lights.strobe lights.beacon master.battery "
    "master.alternator switch.avionics switch parking_brake engine.start"
)


def draft_unknown_device(claude: Claude, device: DetectedDevice, photo: Path | None) -> DeviceDefinition:
    if device.vendor_id is None or device.product_id is None:
        raise ValueError(f"{device.name} has no USB vendor/product id to key a definition on")
    content = [image_block(photo)] if photo else []
    content.append({
        "type": "text",
        "text": (
            f"Device: {json.dumps(device.model_dump(mode='json'))}\n{ROLE_HINT}\n"
            "Draft its controls."
        ),
    })
    draft = claude.structured(system=DRAFT_SYSTEM, content=content, output=DraftControls)
    controls = [c.model_copy(update={"verified": False}) for c in draft.controls if _in_range(c, device)]
    return DeviceDefinition(
        name=device.name,
        vendor_id=device.vendor_id,
        product_id=device.product_id,
        controls=controls,
    )


def _in_range(control: PhysicalControl, device: DetectedDevice) -> bool:
    buttons = [control.button, control.on_button, control.off_button, control.inc_button, control.dec_button]
    return (
        (control.axis is None or control.axis < device.num_axes)
        and (control.hat is None or control.hat < device.num_hats)
        and all(b is None or b < device.num_buttons for b in buttons)
    )
