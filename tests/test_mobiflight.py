from pathlib import Path

import pytest

from msfs_mapper import cli
from msfs_mapper.ai import AIError, Claude
from msfs_mapper.aircraft.templates import profile_from_template
from msfs_mapper.data import function_catalog
from msfs_mapper.mapping.engine import heuristic_map
from msfs_mapper.mobiflight import (
    Identification,
    Identified,
    MobiFlightError,
    ai_identify,
    import_project,
    parse_project,
)
from msfs_mapper.models import AircraftInfo
from msfs_mapper.pipeline import Mapper
from msfs_mapper.profiles.store import Store

from conftest import ALPHA, BRAVO, PEDALS, fake_claude

PROJECT = Path(__file__).parent / "data" / "cockpit.mcc"
A320 = AircraftInfo(title="Airbus A320neo", engine_type=1, engine_count=2, retractable_gear=True)


def by_input(imported):
    return {b.input: b for b in imported.bindings}


def test_parse_reads_active_inputs_only():
    bindings = parse_project(PROJECT)
    assert [b.input for b in bindings] == ["Gear switch", "HDG encoder", "LDG LT", "SEATBELT", "Button 8"]
    gear = bindings[0]
    assert (gear.module, gear.input_type, gear.description) == ("Cockpit Mega", "Button", "Gear lever")
    assert gear.commands == ["(>K:GEAR_DOWN)", "(>K:GEAR_UP)"]


def test_recognises_k_events_and_event_ids(setup):
    imported = import_project(PROJECT, function_catalog(), setup)
    m = by_input(imported)
    assert m["Gear switch"].function == "gear"
    assert m["HDG encoder"].function == "heading_bug"
    assert m["LDG LT"].function == "landing_lights"
    assert m["SEATBELT"].function is None  # add-on L:var, not in the catalog
    assert m["Button 8"].function == "parking_brake"
    # The joystick input is linked to the Bravo we read ourselves (MobiFlight buttons are 1-based).
    assert (m["Button 8"].usb_device, m["Button 8"].button) == ("294B:1901", 7)
    assert m["Gear switch"].usb_device is None


def test_child_element_settings_are_understood():
    xml = """<MobiflightConnector><inputs><config guid="x">
        <active>true</active><description>Flaps</description>
        <settings><serial>Panel/ SN-1</serial><name>Flaps up</name><type>Button</type>
          <button><onPress type="MSFS2020CustomInputAction" command="(&gt;K:FLAPS_DECR)"/></button>
        </settings></config></inputs></MobiflightConnector>"""
    [binding] = parse_project(xml)
    assert (binding.module, binding.input, binding.commands) == ("Panel", "Flaps up", ["(>K:FLAPS_DECR)"])


@pytest.mark.parametrize("text", ["<not xml", "<MobiflightConnector><outputs/></MobiflightConnector>"])
def test_bad_files_raise_mobiflight_error(text):
    with pytest.raises(MobiFlightError):
        parse_project(text)


def test_mapping_leaves_mobiflight_functions_and_buttons_alone(setup):
    imported = import_project(PROJECT, function_catalog(), setup)
    mapping = heuristic_map(setup, profile_from_template(A320), external=imported)
    ours = {b.function: (b.device, b.control) for b in mapping.bindings}
    assert {"gear", "heading_bug", "landing_lights", "parking_brake"}.isdisjoint(ours)
    assert {b.function for b in mapping.external} == {"gear", "heading_bug", "landing_lights", "parking_brake"}
    # Bravo button index 7 (the AP button) belongs to MobiFlight now.
    assert ("294B:1901", "ap_master") not in ours.values()
    # The Bravo gear lever is free for something else, never the gear.
    assert ours.get("gear") is None


def test_pipeline_rebuilds_cached_mapping_when_import_changes(tmp_path):
    mapper = Mapper(Store(tmp_path))
    setup = mapper.setup([ALPHA, BRAVO, PEDALS])
    profile = mapper.aircraft_profile(A320)
    before = mapper.mapping(setup, profile)
    assert any(b.function == "gear" for b in before.bindings)
    mapper.import_mobiflight(PROJECT, setup, profile)
    after = mapper.mapping(setup, profile)
    assert not any(b.function == "gear" for b in after.bindings)
    mapper.store.clear_mobiflight()
    assert any(b.function == "gear" for b in mapper.mapping(setup, profile).bindings)


def test_ai_identifies_only_unrecognised_inputs(setup):
    imported = import_project(PROJECT, function_catalog(), setup)
    seatbelt = [b.input for b in imported.bindings].index("SEATBELT")
    claude, messages = fake_claude(Identification(inputs=[
        Identified(index=seatbelt, function="beacon"),
        Identified(index=0, function="strobe_lights"),  # already recognised: must be ignored
        Identified(index=seatbelt, function="no_such_function"),
    ]))
    result = by_input(ai_identify(claude, imported, function_catalog()))
    assert result["SEATBELT"].function == "beacon"
    assert result["Gear switch"].function == "gear"
    assert "SEATBELT" in messages.calls[0]["messages"][0]["content"][0]["text"]
    assert "Gear switch" not in messages.calls[0]["messages"][0]["content"][0]["text"]


def test_missing_credentials_become_ai_error():
    claude, _ = fake_claude(TypeError("Could not resolve authentication method. Expected one of api_key"))
    with pytest.raises(AIError, match="credentials"):
        ai_identify(claude, import_project(PROJECT, function_catalog()), function_catalog())


def test_cli_import(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_detect", lambda: [ALPHA, BRAVO, PEDALS])
    assert cli.main(["--home", str(tmp_path), "--no-ai", "import-mobiflight", str(PROJECT)]) == 0
    out = capsys.readouterr().out
    assert "Cockpit Mega / Gear switch" in out and "-> gear" in out
    assert "4 functions will be left to MobiFlight" in out
    assert cli.main(["--home", str(tmp_path), "--no-ai", "map", "--title", "Airbus A320neo",
                     "--engine-type", "1", "--engines", "2", "--retractable"]) == 0
    assert "MobiFlight: Cockpit Mega / Gear switch" in capsys.readouterr().out
