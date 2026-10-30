import xml.etree.ElementTree as ET
from pathlib import Path

from msfs_mapper import cli
from msfs_mapper.aircraft.templates import profile_from_template
from msfs_mapper.data import function_catalog
from msfs_mapper.mapping.engine import functions_for, heuristic_map
from msfs_mapper.mobiflight import GENERATED_TAG, import_project, parse_project
from msfs_mapper.mobiflight_export import _inputs, export_project, split
from msfs_mapper.models import (
    AircraftInfo,
    ExternalBinding,
    FunctionActions,
    KeyboardKnob,
    SimAction,
    SimFunction,
)
from msfs_mapper.pipeline import Mapper
from msfs_mapper.profiles.store import Store

from conftest import ALPHA, BRAVO, PEDALS

PROJECT = Path(__file__).parent / "data" / "cockpit.mcc"
A320 = AircraftInfo(title="Airbus A320neo", engine_type=1, engine_count=2, retractable_gear=True)


def exported(tmp_path, setup, imported=None):
    imported = imported or import_project(PROJECT, function_catalog(), setup)
    profile = profile_from_template(A320)
    mapping = heuristic_map(setup, profile, external=imported)
    target = tmp_path / "out.mcc"
    result = export_project(setup, mapping, functions_for(profile), imported, target)
    return result, mapping, ET.parse(target).getroot() if target.exists() else None


def generated(root):
    configs = {}
    for config in root.find("inputs"):
        if GENERATED_TAG in (config.findtext("description") or ""):
            settings = config.find("settings")
            group = settings.find("button")
            group = group if group is not None else settings.find("analog")
            triggers = {t.tag: t.get("command") for t in group}
            configs[settings.get("name")] = (settings.get("serial"), settings.get("type"), triggers)
    return configs


def test_exports_known_joysticks_and_keeps_the_users_project(tmp_path, setup):
    imported = import_project(PROJECT, function_catalog(), setup)
    # Let the mapper own the gear (the sample panel's gear switch would otherwise keep it).
    imported.bindings = [b for b in imported.bindings if b.input != "Gear switch"]
    result, _, root = exported(tmp_path, setup, imported)
    assert result.path == tmp_path / "out.mcc"
    assert {b.device for b in result.exported} == {"294B:1901"}  # MobiFlight knows the Bravo
    assert result.needs_device_id == ["Alpha Flight Controls", "Saitek Pro Flight Rudder Pedals"]
    # The user's own configs survive untouched (5 active + 1 disabled input, 1 output).
    originals = [c for c in root.find("inputs") if GENERATED_TAG not in (c.findtext("description") or "")]
    assert len(originals) == 6 and len(root.find("outputs")) == 1

    configs = generated(root)
    serial = "Bravo Throttle Quadrant / JS-{1234-ABCD}"
    # Two-contact gear lever: one MobiFlight button per position (SDL index + 1).
    assert configs["Button 32"] == (serial, "Button", {"onPress": "(>K:GEAR_DOWN)"})
    assert configs["Button 31"] == (serial, "Button", {"onPress": "(>K:GEAR_UP)"})
    # Encoder = two buttons; levers = axes scaled to the SimConnect range.
    assert configs["Button 16"][2] == {"onPress": "(>K:FLAPS_INCR)"}
    assert configs["Button 15"][2] == {"onPress": "(>K:FLAPS_DECR)"}
    assert configs["Axis X"] == (serial, "AnalogInput", {"onChange": "@ 32768 - 2 / (>K:AXIS_THROTTLE1_SET)"})
    assert "Button 8" not in configs  # reserved: MobiFlight already uses it for the parking brake


def test_single_contact_switch_uses_press_and_release(tmp_path, setup):
    imported = import_project(PROJECT, function_catalog(), setup)
    imported.bindings.append(ExternalBinding(module="Alpha Flight Controls", serial="Alpha Flight Controls / JS-{A}",
                                             input="Button 99", function=None))
    _, _, root = exported(tmp_path, setup, imported)
    configs = generated(root)
    assert configs["Button 25"] == ("Alpha Flight Controls / JS-{A}", "Button",
                                    {"onPress": "(>K:TOGGLE_MASTER_BATTERY)", "onRelease": "(>K:TOGGLE_MASTER_BATTERY)"})


def test_reexport_and_reimport_do_not_feed_back(tmp_path, setup):
    first, _, root = exported(tmp_path, setup)
    # Import the exported file (as a user might), export again: still one set of our configs.
    imported = import_project(tmp_path / "out.mcc", function_catalog(), setup)
    assert [b.input for b in imported.bindings] == [b.input for b in parse_project(PROJECT)]
    second, _, root2 = exported(tmp_path / "again", setup, imported)
    assert len(generated(root2)) == len(generated(root))
    assert len(list(root2.find("inputs"))) == len(list(root.find("inputs")))


def test_nothing_written_when_mobiflight_knows_no_controller(tmp_path, setup):
    imported = import_project(PROJECT, function_catalog(), setup)
    imported.bindings = [b for b in imported.bindings if "JS-" not in b.serial]
    result, mapping, root = exported(tmp_path, setup, imported)
    assert result.path is None and root is None
    assert len(result.kept) == len(mapping.bindings)


def test_calculator_axis_exported_virtual_devices_stay_with_the_bridge(setup):
    from msfs_mapper.models import Binding, MappingProfile
    from msfs_mapper.runtime.keyboard import knob_device

    imported = import_project(PROJECT, function_catalog(), setup)
    functions = {**function_catalog(), "fbw_throttle": SimFunction(
        id="fbw_throttle", name="FBW throttle", actions=FunctionActions(
            axis=SimAction(type="calculator", value="@ (>L:A32NX_THROTTLE)")))}
    setup.devices.insert(0, knob_device(KeyboardKnob(enabled=True)))
    mapping = MappingProfile(aircraft_key="x", setup_fingerprint="y", bindings=[
        Binding(device="294B:1901", control="lever_1", function="fbw_throttle"),
        Binding(device="Keyboard knob", control="knob", function="heading_bug"),
        Binding(device="294B:1901", control="lever_2", function="throttle_2"),
    ])
    result = split(setup, mapping, functions, imported)
    assert [b.control for b in result.exported] == ["lever_1", "lever_2"]
    assert [b.control for b in result.kept] == ["knob"]
    bravo = next(d for d in setup.devices if d.key == "294B:1901")
    lever = next(c for c in bravo.controls if c.id == "lever_1")
    [(_, _, [(_, command)])] = _inputs(lever, functions["fbw_throttle"], invert=False)
    assert command == "@ 32768 - 2 / (>L:A32NX_THROTTLE)"


def test_pipeline_exports_by_default_and_run_skips_exported(tmp_path):
    mapper = Mapper(Store(tmp_path))
    setup = mapper.setup([ALPHA, BRAVO, PEDALS])
    profile = mapper.aircraft_profile(A320)
    mapper.import_mobiflight(PROJECT, setup, profile)
    mapping = mapper.mapping(setup, profile)
    path = tmp_path / "mobiflight" / "cockpit - Airbus A320neo.mcc"
    assert mapper.last_export.path == path and path.exists()
    routed = mapper.routed_mapping(setup, profile, mapping)
    assert all(b.device != "294B:1901" for b in routed.bindings)
    assert any(b.device == "294B:1900" for b in routed.bindings)

    mapper.store.save_settings(mapper.store.load_settings().model_copy(update={"export_mobiflight": False}))
    assert mapper.routed_mapping(setup, profile, mapping) == mapping
    assert mapper.export_mobiflight(setup, profile, mapping) is None


def test_cli_export_setting_and_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_detect", lambda: [ALPHA, BRAVO, PEDALS])
    home = ["--home", str(tmp_path), "--no-ai"]
    assert cli.main(home + ["import-mobiflight", str(PROJECT)]) == 0
    assert cli.main(home + ["map", "--title", "Airbus A320neo", "--engine-type", "1",
                            "--engines", "2", "--retractable"]) == 0
    out = capsys.readouterr().out
    assert "MobiFlight project:" in out and "Alpha Flight Controls: not exported yet" in out
    assert cli.main(home + ["mobiflight-export", "--off"]) == 0
    assert "MobiFlight export is off" in capsys.readouterr().out
    assert not Store(tmp_path).load_settings().export_mobiflight
