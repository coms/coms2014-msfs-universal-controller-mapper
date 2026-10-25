"""Core data model shared by every stage of the pipeline.

The pipeline is:

    USB devices + setup photo  ->  ControllerSetup   (what hardware is where)
    loaded aircraft            ->  AircraftProfile   (what the checklists need)
    both                       ->  MappingProfile    (which control drives which function)
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ControlKind(str, Enum):
    """How a physical control behaves electrically, which decides what it can drive."""

    AXIS = "axis"          # continuous lever / yoke / pedal
    BUTTON = "button"      # momentary push button
    SWITCH = "switch"      # maintained two-position toggle (on button, optional off button)
    ENCODER = "encoder"    # rotary knob reported as an inc and a dec button
    HAT = "hat"            # 8-way POV hat


class PhysicalControl(BaseModel):
    """One control on a device, addressed by its HID indices."""

    id: str = Field(description="Stable id within the device, e.g. 'gear_lever'")
    kind: ControlKind
    label: str = Field(default="", description="Text printed on or next to the control")
    # Semantic hints the mapper matches against SimFunction.roles, e.g. "gear", "lights.landing".
    roles: list[str] = Field(default_factory=list)
    axis: int | None = None
    button: int | None = None
    on_button: int | None = None
    off_button: int | None = None
    inc_button: int | None = None
    dec_button: int | None = None
    hat: int | None = None
    verified: bool = Field(default=False, description="Indices confirmed with `msfs-mapper learn`")


class DeviceDefinition(BaseModel):
    """Catalog entry describing a controller model."""

    name: str
    manufacturer: str = ""
    vendor_id: int
    product_id: int
    # Where this kind of device usually sits; a setup photo can override it.
    default_position: str = "center"
    controls: list[PhysicalControl] = Field(default_factory=list)

    @property
    def usb_id(self) -> str:
        return f"{self.vendor_id:04X}:{self.product_id:04X}"


class DetectedDevice(BaseModel):
    """A game controller found on USB right now."""

    index: int = Field(description="SDL joystick index used to open the device")
    name: str
    vendor_id: int | None = None
    product_id: int | None = None
    num_axes: int = 0
    num_buttons: int = 0
    num_hats: int = 0
    guid: str = ""

    @property
    def usb_id(self) -> str | None:
        if self.vendor_id is None or self.product_id is None:
            return None
        return f"{self.vendor_id:04X}:{self.product_id:04X}"


class SetupDevice(BaseModel):
    """A detected device joined with its catalog definition and physical placement."""

    detected: DetectedDevice
    definition: DeviceDefinition | None = None
    position: str = "center"

    @property
    def key(self) -> str:
        return self.detected.usb_id or self.detected.name

    @property
    def controls(self) -> list[PhysicalControl]:
        return self.definition.controls if self.definition else []


class ControllerSetup(BaseModel):
    devices: list[SetupDevice] = Field(default_factory=list)

    def fingerprint(self) -> str:
        """Identifies a hardware combination so mappings can be reused across sessions."""
        return "+".join(sorted(d.key for d in self.devices))


# ---------------------------------------------------------------------------
# Simulator side
# ---------------------------------------------------------------------------


class SimAction(BaseModel):
    """Something the bridge sends to the sim."""

    type: Literal["event", "calculator"] = "event"
    # For type=event: a SimConnect key event name, e.g. "GEAR_UP".
    # For type=calculator: RPN calculator code, e.g. "(>H:A320_Neo_MFD_BTN_CSTR_1)".
    value: str


class FunctionActions(BaseModel):
    """How a function is driven from each kind of physical control. Unset = not supported."""

    axis: SimAction | None = None
    press: SimAction | None = None       # button / switch toggling
    on: SimAction | None = None          # switch to ON position
    off: SimAction | None = None         # switch to OFF position
    inc: SimAction | None = None         # encoder clockwise / hat up
    dec: SimAction | None = None         # encoder counter-clockwise / hat down

    def supports(self, kind: ControlKind) -> bool:
        match kind:
            case ControlKind.AXIS:
                return self.axis is not None
            case ControlKind.SWITCH:
                return (self.on is not None and self.off is not None) or self.press is not None
            case ControlKind.BUTTON:
                return self.press is not None
            case ControlKind.ENCODER | ControlKind.HAT:
                return self.inc is not None and self.dec is not None
        return False


class SimFunction(BaseModel):
    """An aircraft function a pilot needs a control for (gear, landing lights, throttle 1...)."""

    id: str
    name: str
    roles: list[str] = Field(default_factory=list)
    # Preferred control kinds, best first. A maintained switch is the natural fit for lights.
    preferred_kinds: list[ControlKind] = Field(default_factory=list)
    actions: FunctionActions


class ChecklistItem(BaseModel):
    challenge: str
    response: str = ""
    function: str | None = Field(default=None, description="SimFunction id this step operates")


class Checklist(BaseModel):
    phase: Literal["before_takeoff", "takeoff", "approach", "landing", "after_landing"]
    items: list[ChecklistItem]


class AircraftInfo(BaseModel):
    """What the sim tells us about the loaded aircraft."""

    title: str
    atc_model: str = ""
    atc_type: str = ""
    category: str = ""  # SimConnect CATEGORY: Airplane / Helicopter / Glider
    engine_type: int | None = None  # 0 piston, 1 jet, 2 none, 3 helo turbine, 5 turboprop
    engine_count: int = 1
    retractable_gear: bool = False
    flaps_positions: int = 0

    @property
    def key(self) -> str:
        return "".join(c.lower() if c.isalnum() else "-" for c in self.title).strip("-")


class AircraftProfile(BaseModel):
    """Which functions matter for this aircraft and in what priority order."""

    aircraft: AircraftInfo
    template: str = Field(description="Checklist template id the profile was built from")
    # Function ids, highest priority first. Axis functions in cockpit order (left to right).
    functions: list[str]
    checklists: list[Checklist] = Field(default_factory=list)
    # Aircraft-specific functions (e.g. add-on L:var/H:event controls) not in the base catalog.
    custom_functions: list[SimFunction] = Field(default_factory=list)
    notes: str = ""


class Binding(BaseModel):
    device: str = Field(description="SetupDevice.key")
    control: str = Field(description="PhysicalControl.id")
    function: str = Field(description="SimFunction id")
    invert: bool = False
    locked: bool = Field(default=False, description="User-pinned; never changed by re-mapping")
    reason: str = ""


class MappingProfile(BaseModel):
    aircraft_key: str
    setup_fingerprint: str
    bindings: list[Binding] = Field(default_factory=list)
    unassigned_functions: list[str] = Field(default_factory=list)
    source: Literal["heuristic", "ai", "user"] = "heuristic"
