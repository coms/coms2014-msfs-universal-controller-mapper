import sys

import pytest

from msfs_mapper import cli
from msfs_mapper.models import AircraftInfo, KeyboardKnob
from msfs_mapper.pipeline import Mapper
from msfs_mapper.profiles.store import Store
from msfs_mapper.runtime.bridge import LogExecutor, Router
from msfs_mapper.mapping.engine import functions_for
from msfs_mapper.runtime.inputs import ButtonChanged
from msfs_mapper.runtime.keyboard import DEC, INC, KEYBOARD_INDEX, PRESS, KeyboardKnobHook, KnobDecoder

from conftest import ALPHA, BRAVO, PEDALS

VOLUME_UP, VOLUME_DOWN, MUTE = 0xAF, 0xAE, 0xAD
C172 = AircraftInfo(title="Cessna Skyhawk", engine_type=0, engine_count=1)


def test_decoder_maps_volume_keys_and_leaves_mute_alone_by_default():
    decoder = KnobDecoder(KeyboardKnob(enabled=True))
    assert decoder.decode(VOLUME_UP, True) == ButtonChanged(KEYBOARD_INDEX, INC, True)
    assert decoder.decode(VOLUME_DOWN, False) == ButtonChanged(KEYBOARD_INDEX, DEC, False)
    assert decoder.decode(MUTE, True) is None
    assert decoder.decode(0x41, True) is None  # the letter A is never touched
    with_press = KnobDecoder(KeyboardKnob(enabled=True, press_role="autopilot.master"))
    assert with_press.decode(MUTE, True) == ButtonChanged(KEYBOARD_INDEX, PRESS, True)


def test_f13_preset():
    decoder = KnobDecoder(KeyboardKnob(enabled=True, keys="f13"))
    assert decoder.decode(0x7C, True).button == INC and decoder.decode(0x7D, True).button == DEC


def mapped(tmp_path, knob, devices=(ALPHA, BRAVO, PEDALS)):
    mapper = Mapper(Store(tmp_path))
    mapper.store.save_keyboard(knob)
    setup = mapper.setup(list(devices))
    profile = mapper.aircraft_profile(C172)
    mapping = mapper.mapping(setup, profile)
    return setup, profile, mapping, {b.function: (b.device, b.control) for b in mapping.bindings}


def test_disabled_knob_is_not_part_of_the_setup(tmp_path):
    setup, *_ = mapped(tmp_path, KeyboardKnob(enabled=False))
    assert all(d.detected.index != KEYBOARD_INDEX for d in setup.devices)


def test_chosen_role_beats_other_encoders(tmp_path):
    *_, m = mapped(tmp_path, KeyboardKnob(enabled=True, knob_role="encoder.hdg", press_role="autopilot.master"))
    assert m["heading_bug"] == ("Keyboard knob", "knob")
    assert m["ap_master"] == ("Keyboard knob", "knob_press")
    assert m["ap_altitude_select"] == ("294B:1901", "ap_knob")  # Bravo knob moves on to altitude


def test_automatic_role_takes_a_leftover_encoder_function(tmp_path):
    *_, m = mapped(tmp_path, KeyboardKnob(enabled=True))
    assert m["heading_bug"] == ("294B:1901", "ap_knob")
    assert m["ap_altitude_select"] == ("Keyboard knob", "knob")
    assert ("Keyboard knob", "knob_press") not in m.values()


def test_knob_alone_can_drive_trim(tmp_path):
    *_, m = mapped(tmp_path, KeyboardKnob(enabled=True, knob_role="trim.pitch"), devices=(PEDALS,))
    assert m["elevator_trim"] == ("Keyboard knob", "knob")


def test_router_turns_knob_into_sim_events(tmp_path):
    setup, profile, mapping, _ = mapped(tmp_path, KeyboardKnob(enabled=True, knob_role="encoder.hdg"))
    executor = LogExecutor()
    router = Router(setup, mapping, functions_for(profile), executor)
    assert router.handles(KEYBOARD_INDEX, INC) and not router.handles(KEYBOARD_INDEX, PRESS)
    decoder = KnobDecoder(KeyboardKnob(enabled=True))
    router.run(e for e in [decoder.decode(VOLUME_UP, True), decoder.decode(VOLUME_UP, False),
                           decoder.decode(VOLUME_DOWN, True)] if e)
    assert executor.sent == [("HEADING_BUG_INC", 0), ("HEADING_BUG_DEC", 0)]


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows guard")
def test_hook_refuses_to_start_off_windows():
    with pytest.raises(OSError, match="Windows"):
        KeyboardKnobHook(KeyboardKnob(enabled=True), capture=lambda _: True)


def test_cli_configures_knob(tmp_path, capsys):
    assert cli.main(["--home", str(tmp_path), "keyboard-knob", "--enable", "--drives", "alt",
                     "--press", "ap-disconnect", "--no-suppress"]) == 0
    knob = Store(tmp_path).load_keyboard()
    assert (knob.enabled, knob.knob_role, knob.press_role, knob.suppress) == (
        True, "encoder.alt", "autopilot.disconnect", False)
    assert "Selected altitude" in capsys.readouterr().out
    assert cli.main(["--home", str(tmp_path), "keyboard-knob", "--disable"]) == 0
    assert Store(tmp_path).load_keyboard().knob_role == "encoder.alt"  # other settings kept
