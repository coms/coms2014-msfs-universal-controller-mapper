"""Drives the real Tk window. Skipped where Tk or a display is unavailable (e.g. headless CI);
run under `xvfb-run` to include it."""

from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from msfs_mapper.gui import NOT_RECOGNISED, App  # noqa: E402
from msfs_mapper.profiles.store import Store  # noqa: E402

from conftest import ALPHA, BRAVO, PEDALS  # noqa: E402

PROJECT = Path(__file__).parent / "data" / "cockpit.mcc"


@pytest.fixture
def app(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    app = App(root, Store(tmp_path), detect=lambda: [ALPHA, BRAVO, PEDALS])
    app.use_ai.set(False)
    app.alerts = []
    app.alert = lambda text, error=False: app.alerts.append(text)
    app.wait_idle()
    yield app
    root.destroy()


def rows(tree):
    return [tree.item(i, "values") for i in tree.get_children()]


def test_devices_listed(app):
    assert [r[0] for r in rows(app.devices)] == [
        "Alpha Flight Controls", "Bravo Throttle Quadrant", "Saitek Pro Flight Rudder Pedals"]


def test_import_then_map_shows_mobiflight_rows(app):
    app.title.set("Airbus A320neo")
    app.engine.set("Jet")
    app.engines.set(2)
    app.retractable.set(True)
    app.build_mapping(False)
    app.wait_idle()
    assert ("Landing gear", "Bravo Throttle Quadrant", "gear_lever", "auto") in rows(app.mapping_tree)

    app.import_mobiflight(PROJECT)
    app.wait_idle()
    assert not app.alerts
    mf = rows(app.mf_tree)
    assert ("Cockpit Mega", "Gear switch", "Button", "Gear lever", "Landing gear",
            "(>K:GEAR_DOWN); (>K:GEAR_UP)") in mf
    assert any(r[1] == "SEATBELT" and r[4] == NOT_RECOGNISED for r in mf)
    assert [r[:2] for r in rows(app.devices)[3:]] == [("Cockpit Mega", "MobiFlight"), ("Overhead Nano", "MobiFlight")]

    # Import triggers a rebuild: gear is now MobiFlight's.
    mapping = rows(app.mapping_tree)
    assert ("Landing gear", "Cockpit Mega", "Gear switch", "MobiFlight") in mapping
    assert not any(r[0] == "Landing gear" and r[3] == "auto" for r in mapping)


def test_manual_function_assignment_and_lock(app):
    app.title.set("Cessna 172")
    app.build_mapping(False)
    app.wait_idle()
    app.import_mobiflight(PROJECT)
    app.wait_idle()
    seatbelt = next(i for i in app.mf_tree.get_children() if app.mf_tree.item(i, "values")[1] == "SEATBELT")
    app.set_mobiflight_function(int(seatbelt), "beacon")
    app.wait_idle()
    assert app.mf_tree.item(seatbelt, "values")[4] == "Beacon light"
    assert ("Beacon light", "Overhead Nano", "SEATBELT", "MobiFlight") in rows(app.mapping_tree)

    first = app.mapping_tree.get_children()[0]
    app.mapping_tree.selection_set(first)
    app.toggle_lock()
    assert app.mapping_tree.item(first, "values")[3] == "locked"


def test_bad_project_reports_error(app, tmp_path):
    bad = tmp_path / "broken.mcc"
    bad.write_text("<nope")
    app.import_mobiflight(bad)
    app.wait_idle()
    assert app.alerts and "broken.mcc" in app.alerts[0]
