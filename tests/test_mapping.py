from msfs_mapper.aircraft.templates import profile_from_template
from msfs_mapper.mapping.engine import heuristic_map
from msfs_mapper.models import AircraftInfo, Binding, MappingProfile

C172 = AircraftInfo(title="Cessna Skyhawk G1000", engine_type=0, engine_count=1)
A320 = AircraftInfo(title="Airbus A320neo", engine_type=1, engine_count=2, retractable_gear=True)


def by_function(mapping):
    return {b.function: (b.device, b.control) for b in mapping.bindings}


def test_single_piston_on_alpha_bravo_pedals(setup):
    profile = profile_from_template(C172)
    assert "gear" not in profile.functions  # fixed gear
    m = by_function(heuristic_map(setup, profile))
    assert m["roll"] == ("294B:1900", "yoke_roll")
    assert m["pitch"] == ("294B:1900", "yoke_pitch")
    assert m["yaw"] == ("06A3:0763", "rudder")
    # Levers keep cockpit order: throttle, prop, mixture on levers 1-3.
    assert [m[f][1] for f in ("throttle", "propeller", "mixture")] == ["lever_1", "lever_2", "lever_3"]
    assert m["landing_lights"] == ("294B:1900", "light_land")
    assert m["battery"] == ("294B:1900", "master_bat")
    assert m["flaps"] == ("294B:1901", "flaps_lever")
    assert m["heading_bug"] == ("294B:1901", "ap_knob")
    assert m["ap_disconnect"] == ("294B:1900", "yoke_left_red")


def test_airliner_gets_split_throttles_gear_and_speedbrake(setup):
    profile = profile_from_template(A320)
    mapping = heuristic_map(setup, profile)
    m = by_function(mapping)
    assert m["throttle_1"][1] == "lever_1" and m["throttle_2"][1] == "lever_2"
    assert m["speedbrake"][1] == "lever_3"
    assert m["gear"] == ("294B:1901", "gear_lever")
    assert "throttle" not in m
    controls = [(b.device, b.control) for b in mapping.bindings]
    assert len(controls) == len(set(controls)), "a control is bound twice"


def test_helicopter_category_selects_helicopter_profile():
    helicopter = AircraftInfo(
        title="Robinson R44", engine_type=3, engine_count=1, category="Helicopter"
    )
    profile = profile_from_template(helicopter)
    assert profile.template == "helicopter"
    assert {"roll", "pitch", "yaw", "collective", "rotor_clutch", "rotor_governor"} <= set(
        profile.functions
    )
    assert "throttle" not in profile.functions
    assert profile.checklists


def test_incompatible_kinds_never_bound(setup):
    from msfs_mapper.mapping.engine import functions_for

    profile = profile_from_template(A320)
    mapping = heuristic_map(setup, profile)
    controls = {(d.key, c.id): c for d in setup.devices for c in d.controls}
    functions = functions_for(profile)
    for b in mapping.bindings:
        assert functions[b.function].actions.supports(controls[(b.device, b.control)].kind)


def test_locked_binding_survives_remap(setup):
    profile = profile_from_template(C172)
    previous = MappingProfile(
        aircraft_key=C172.key, setup_fingerprint=setup.fingerprint(),
        bindings=[Binding(device="294B:1901", control="toggle_1", function="landing_lights", locked=True)],
    )
    m = by_function(heuristic_map(setup, profile, previous))
    assert m["landing_lights"] == ("294B:1901", "toggle_1")
    # The Alpha LAND switch is dedicated hardware, so it stays free rather than driving something else.
    assert ("294B:1900", "light_land") not in m.values()


def test_functions_without_hardware_are_reported(tmp_path):
    from msfs_mapper.devices.catalog import DeviceCatalog
    from msfs_mapper.devices.discovery import build_setup
    from conftest import PEDALS

    setup = build_setup([PEDALS], DeviceCatalog(tmp_path))
    mapping = heuristic_map(setup, profile_from_template(C172))
    assert {"yaw", "brake_left", "brake_right"} == set(by_function(mapping))
    assert "throttle" in mapping.unassigned_functions


def test_four_engine_jet_gets_four_throttles_on_bravo_levers(setup):
    b747 = AircraftInfo(title="Boeing 747-8", engine_type=1, engine_count=4, retractable_gear=True)
    m = by_function(heuristic_map(setup, profile_from_template(b747)))
    assert [m[f"throttle_{n}"] for n in (1, 2, 3, 4)] == [
        ("294B:1901", f"lever_{n}") for n in (1, 2, 3, 4)]


def test_piston_twin_gets_split_throttles():
    baron = AircraftInfo(title="Beechcraft Baron G58", engine_type=0, engine_count=2, retractable_gear=True)
    functions = profile_from_template(baron).functions
    assert {"throttle_1", "throttle_2"} <= set(functions)
    assert not {"throttle", "throttle_3", "throttle_4"} & set(functions)
