import anthropic
import httpx2
import pytest

from msfs_mapper.ai import AIError
from msfs_mapper.aircraft.knowledge import AircraftAdvice, advise
from msfs_mapper.aircraft.templates import profile_from_template
from msfs_mapper.mapping.ai_mapper import ProposedBinding, ProposedMapping, ai_map
from msfs_mapper.models import AircraftInfo
from msfs_mapper.vision.layout import SeenDevice, SetupPhoto, apply_photo, draft_unknown_device, DraftControls
from msfs_mapper.models import PhysicalControl, ControlKind

from conftest import UNKNOWN, fake_claude

A320 = AircraftInfo(title="Airbus A320neo", engine_type=1, engine_count=2, retractable_gear=True)


def test_ai_mapping_accepts_valid_and_rejects_invalid(setup):
    proposal = ProposedMapping(bindings=[
        # valid: user's preference for the landing lights on a Bravo toggle
        ProposedBinding(device="294B:1901", control="toggle_1", function="landing_lights", reason="r"),
        # invalid: axis function on a button
        ProposedBinding(device="294B:1901", control="ap_hdg", function="throttle_1", reason="r"),
        # invalid: control that does not exist
        ProposedBinding(device="294B:1901", control="lever_99", function="gear", reason="r"),
        # invalid: same control twice
        ProposedBinding(device="294B:1901", control="toggle_1", function="strobe_lights", reason="r"),
    ])
    claude, messages = fake_claude(proposal)
    mapping = ai_map(claude, setup, profile_from_template(A320))
    m = {b.function: b.control for b in mapping.bindings}
    assert mapping.source == "ai"
    assert m["landing_lights"] == "toggle_1"
    assert m["throttle_1"] == "lever_1"  # back-filled from heuristic, not the bogus AI binding
    assert m["gear"] == "gear_lever"
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert call["output_format"] is ProposedMapping


def test_advise_drops_unknown_function_ids():
    advice = AircraftAdvice(
        template="jet_twin", functions=["throttle_1", "throttle_2", "made_up", "gear"],
        checklists=[], custom_functions=[], notes="FBW: use detents",
    )
    claude, _ = fake_claude(advice)
    profile = advise(claude, A320)
    assert profile.functions == ["throttle_1", "throttle_2", "gear"]
    assert profile.notes == "FBW: use detents"
    assert profile.checklists  # falls back to the template's checklists


def test_api_errors_become_ai_errors(setup):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    claude, _ = fake_claude(anthropic.APIConnectionError(request=request))
    with pytest.raises(AIError):
        ai_map(claude, setup, profile_from_template(A320))


def test_photo_positions_are_applied(setup):
    photo = SetupPhoto(devices=[
        SeenDevice(manufacturer="Honeycomb", model="Bravo Throttle Quadrant", position="left", visible_labels=[], usb_name=""),
        SeenDevice(manufacturer="Virpil", model="Control Panel #2", position="right", visible_labels=[], usb_name=""),
    ], notes="")
    unmatched = apply_photo(setup, photo)
    assert {d.key: d.position for d in setup.devices}["294B:1901"] == "left"
    assert [u.model for u in unmatched] == ["Control Panel #2"]


def test_drafted_device_drops_out_of_range_controls():
    draft = DraftControls(controls=[
        PhysicalControl(id="b1", kind=ControlKind.BUTTON, button=0, verified=True),
        PhysicalControl(id="b99", kind=ControlKind.BUTTON, button=99),
    ])
    claude, _ = fake_claude(draft)
    definition = draft_unknown_device(claude, UNKNOWN, None)
    assert [c.id for c in definition.controls] == ["b1"]
    assert definition.controls[0].verified is False
    assert definition.usb_id == "1234:0001"


def _decode(block):
    import base64
    import io

    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))


def test_image_block_downscales_large_photos(tmp_path):
    from PIL import Image

    from msfs_mapper.ai import MAX_IMAGE_EDGE, image_block

    path = tmp_path / "setup.png"
    Image.new("RGBA", (4000, 3000), (10, 20, 30, 255)).save(path)
    block = image_block(path)
    assert block["source"]["media_type"] == "image/jpeg"
    assert _decode(block).size == (MAX_IMAGE_EDGE, MAX_IMAGE_EDGE * 3 // 4)


def test_image_block_keeps_small_photos_and_applies_exif_rotation(tmp_path):
    from PIL import Image

    from msfs_mapper.ai import image_block

    path = tmp_path / "setup.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90° clockwise to display
    Image.new("RGB", (800, 600)).save(path, exif=exif)
    assert _decode(image_block(path)).size == (600, 800)


def test_image_block_rejects_unreadable_file(tmp_path):
    from msfs_mapper.ai import image_block

    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")
    with pytest.raises(AIError):
        image_block(path)


def test_saved_api_key_overrides_environment(monkeypatch):
    from msfs_mapper.ai import Claude

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    assert Claude(api_key="sk-ant-saved").client.api_key == "sk-ant-saved"
    assert Claude().client.api_key == "sk-ant-env"
