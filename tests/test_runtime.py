from msfs_mapper.aircraft.templates import profile_from_template
from msfs_mapper.mapping.engine import functions_for, heuristic_map
from msfs_mapper.models import AircraftInfo, ControlKind
from msfs_mapper.pipeline import Mapper
from msfs_mapper.profiles.store import Store
from msfs_mapper.runtime.bridge import LogExecutor, Router
from msfs_mapper.runtime.inputs import AxisMoved, ButtonChanged
from msfs_mapper.runtime.learn import learn_device

from conftest import ALPHA, BRAVO, PEDALS

A320 = AircraftInfo(title="Airbus A320neo", engine_type=1, engine_count=2, retractable_gear=True)


def router_for(setup):
    profile = profile_from_template(A320)
    executor = LogExecutor()
    return Router(setup, heuristic_map(setup, profile), functions_for(profile), executor), executor


def test_router_sends_axis_switch_and_encoder_events(setup):
    router, executor = router_for(setup)
    router.run([
        AxisMoved(device=1, axis=0, value=1.0),          # Bravo lever 1 -> throttle 1
        AxisMoved(device=1, axis=0, value=1.0001),       # inside deadband: ignored
        ButtonChanged(device=1, button=31, pressed=True),  # gear lever down
        ButtonChanged(device=1, button=30, pressed=True),  # gear lever up
        ButtonChanged(device=1, button=15, pressed=True),  # flaps lever down a notch
        ButtonChanged(device=0, button=29, pressed=True),  # Alpha LAND on
        ButtonChanged(device=0, button=29, pressed=False), # Alpha LAND off (single contact)
        ButtonChanged(device=1, button=31, pressed=False), # releases are ignored for two-contact switches
    ])
    assert executor.sent == [
        ("AXIS_THROTTLE1_SET", 16383),
        ("GEAR_DOWN", 0),
        ("GEAR_UP", 0),
        ("FLAPS_INCR", 0),
        ("LANDING_LIGHTS_ON", 0),
        ("LANDING_LIGHTS_OFF", 0),
    ]


def test_mapping_is_cached_per_aircraft_and_setup(tmp_path):
    mapper = Mapper(Store(tmp_path))
    setup = mapper.setup([ALPHA, BRAVO, PEDALS])
    profile = mapper.aircraft_profile(A320)
    first = mapper.mapping(setup, profile)
    first.bindings[0].locked = True
    mapper.store.save_mapping(first)
    again = mapper.mapping(setup, mapper.aircraft_profile(A320))
    assert again.bindings[0].locked
    # A different hardware set gets its own mapping.
    other = mapper.mapping(mapper.setup([PEDALS]), profile)
    assert other.setup_fingerprint != first.setup_fingerprint


def test_learn_updates_indices_and_marks_verified(setup):
    pedals = setup.devices[2].definition
    scripted = iter([
        [AxisMoved(2, 5, 0.0), AxisMoved(2, 5, 0.9)],    # left toe brake is really axis 5
        [],                                             # right toe brake: user skipped
        [ButtonChanged(2, 1, True), AxisMoved(2, 2, -1.0), AxisMoved(2, 2, 0.0), AxisMoved(2, 2, 1.0)],
    ])
    learned = learn_device(pedals, 2, lambda timeout: iter(next(scripted)), prompt=lambda _: None)
    by_id = {c.id: c for c in learned.controls}
    assert by_id["toe_left"].axis == 5 and by_id["toe_left"].verified
    assert by_id["toe_right"].axis == 1 and not by_id["toe_right"].verified
    assert by_id["rudder"].axis == 2 and by_id["rudder"].kind is ControlKind.AXIS
