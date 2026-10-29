from msfs_mapper.data import function_catalog
from msfs_mapper.devices.catalog import DeviceCatalog, builtin_definitions
from msfs_mapper.devices.discovery import build_setup, parse_sdl_guid
from msfs_mapper.devices.mobiflight import mega_definition
from msfs_mapper.models import ControlKind, DetectedDevice

from conftest import ALPHA, UNKNOWN


def test_function_catalog_loads_and_every_function_is_drivable():
    catalog = function_catalog()
    assert {"gear", "flaps", "throttle", "landing_lights", "ap_master"} <= catalog.keys()
    for fn in catalog.values():
        assert fn.preferred_kinds, fn.id
        assert any(fn.actions.supports(k) for k in fn.preferred_kinds), fn.id


def test_device_controls_have_indices_for_their_kind():
    for definition in builtin_definitions():
        ids = [c.id for c in definition.controls]
        assert len(ids) == len(set(ids)), definition.name
        for c in definition.controls:
            match c.kind:
                case ControlKind.AXIS:
                    assert c.axis is not None
                case ControlKind.BUTTON:
                    assert c.button is not None
                case ControlKind.SWITCH:
                    assert c.on_button is not None
                case ControlKind.ENCODER:
                    assert c.inc_button is not None and c.dec_button is not None
                case ControlKind.HAT:
                    assert c.hat is not None


def test_parse_sdl_guid_extracts_usb_ids():
    # bus=0x0003 (USB), crc=0, vendor=0x294B, product=0x1901, version=0x0110
    guid = "03000000" "4b290000" "01190000" "10010000"
    assert parse_sdl_guid(guid) == (0x294B, 0x1901)
    assert parse_sdl_guid("05000000" "00000000" "00000000" "00000000") == (None, None)
    assert parse_sdl_guid("nonsense") == (None, None)


def test_user_definition_overrides_builtin(tmp_path):
    catalog = DeviceCatalog(tmp_path)
    alpha = catalog.lookup("294B:1900")
    learned = alpha.model_copy(update={"name": "My Alpha"})
    catalog.save(learned)
    assert DeviceCatalog(tmp_path).lookup("294B:1900").name == "My Alpha"


def test_build_setup_marks_unknown_devices(tmp_path):
    setup = build_setup([ALPHA, UNKNOWN], DeviceCatalog(tmp_path))
    assert setup.devices[0].definition.name == "Alpha Flight Controls"
    assert setup.devices[1].definition is None
    assert setup.fingerprint() == "1234:0001+294B:1900"


def test_logitech_throttle_quadrant_is_recognized_by_usb_id(tmp_path):
    detected = DetectedDevice(
        index=4,
        name="Saitek Pro Flight Throttle Quadrant",
        vendor_id=0x06A3,
        product_id=0x0C2D,
        num_axes=3,
        num_buttons=6,
    )
    setup = build_setup([detected], DeviceCatalog(tmp_path / "devices"))
    definition = setup.devices[0].definition

    assert definition is not None
    assert definition.name == "Pro Flight Throttle Quadrant"
    assert [control.axis for control in definition.controls[:3]] == [0, 1, 2]
    assert [control.button for control in definition.controls[3:]] == list(range(6))
    assert all(not control.verified for control in definition.controls)


def test_vkb_gladiator_is_recognized_by_usb_id(tmp_path):
    detected = DetectedDevice(
        index=4,
        name="VKB-Sim Gladiator NXT EVO",
        vendor_id=0x231D,
        product_id=0x0200,
        num_axes=6,
        num_buttons=32,
        num_hats=1,
    )
    setup = build_setup([detected], DeviceCatalog(tmp_path / "devices"))
    definition = setup.devices[0].definition

    assert definition is not None
    assert definition.name == "Gladiator NXT / EVO"
    assert [control.axis for control in definition.controls if control.kind is ControlKind.AXIS] == list(range(6))
    assert [control.button for control in definition.controls if control.kind is ControlKind.BUTTON] == list(range(32))
    assert definition.controls[6].kind is ControlKind.HAT
    assert all(not control.verified for control in definition.controls)


def test_mobiflight_mega_definition_uses_sequential_event_indices():
    definition = mega_definition(buttons=3, encoders=2)
    assert [control.button for control in definition.controls[:3]] == [0, 1, 2]
    assert [(control.inc_button, control.dec_button) for control in definition.controls[3:]] == [
        (3, 4),
        (5, 6),
    ]
