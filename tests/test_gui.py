"""Drives the real Tk window. Skipped where Tk or a display is unavailable (e.g. headless CI);
run under `xvfb-run` to include it."""

import gc
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
    del app, root
    # Collect this window's Tk variables now, on the main thread. Left for later, a worker
    # thread may collect them, and Tkinter then waits ~1s per variable for a main loop.
    gc.collect()


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
    assert ("Cockpit Mega", "Gear switch", "switch / lever (Button)", "Gear lever", "Landing gear",
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


def test_keyboard_knob_settings(app):
    from msfs_mapper.models import KeyboardKnob

    app.title.set("Cessna 172")
    app.build_mapping(False)
    app.wait_idle()
    app.save_knob(KeyboardKnob(enabled=True, knob_role="encoder.hdg"))
    app.wait_idle()
    assert rows(app.devices)[0][:2] == ("Keyboard knob", "Keyboard keys")
    assert ("Heading bug", "Keyboard knob", "knob", "auto") in rows(app.mapping_tree)

    app.open_knob_dialog()  # builds without errors
    app.root.update()


def test_sharing_checkbox(app):
    app.title.set("Cessna 172")
    app.import_mobiflight(PROJECT)
    app.wait_idle()
    app.build_mapping(False)
    app.wait_idle()
    heading = [r for r in rows(app.mapping_tree) if r[0] == "Heading bug"]
    assert heading == [("Heading bug", "Cockpit Mega", "HDG encoder", "MobiFlight")]
    assert app.mf_tree.item("1", "values")[2] == "button / knob (Encoder)"

    app.share_mf.set(True)
    app.set_mobiflight_sharing(True)
    app.wait_idle()
    heading = [r for r in rows(app.mapping_tree) if r[0] == "Heading bug"]
    assert heading == [("Heading bug", "Bravo Throttle Quadrant", "ap_knob", "auto, run by MobiFlight"),
                       ("Heading bug", "Cockpit Mega", "HDG encoder", "MobiFlight")]


def test_export_checkbox(app):
    app.title.set("Cessna 172")
    app.import_mobiflight(PROJECT)
    app.wait_idle()
    app.build_mapping(False)
    app.wait_idle()
    assert app.export_mf.get()  # on by default
    assert "controls written to" in app.export_info.get()
    assert "Alpha Flight Controls: configure any one input" in app.export_info.get()
    sources = {r[2]: r[3] for r in rows(app.mapping_tree) if r[1] == "Bravo Throttle Quadrant"}
    assert sources["lever_1"] == "auto, run by MobiFlight"

    app.export_mf.set(False)
    app.set_export(False)
    app.wait_idle()
    assert app.export_info.get().startswith("Off")
    sources = {r[2]: r[3] for r in rows(app.mapping_tree) if r[1] == "Bravo Throttle Quadrant"}
    assert sources["lever_1"] == "auto"


def test_mega_pins_dialog(app):
    import json

    saved = app.save_mega_pins("30, 31", "2, 3; 18, 19")
    assert json.loads(saved.read_text()) == {"button_pins": [30, 31], "encoder_pins": [[2, 3], [18, 19]]}
    with pytest.raises(ValueError):
        app.save_mega_pins("22", "4, 5")  # not interrupt pins
    app.configure_mega()  # builds without errors, prefilled from the saved file
    app.root.update()


def test_settings_stay_visible_in_a_small_window(app):
    app.root.geometry("900x560")
    app.tabs.select(1)
    for _ in range(5):
        app.root.update()
    mf_tab = app.tabs.nametowidget(app.tabs.tabs()[1])
    panel = next(w for w in mf_tab.winfo_children() if isinstance(w, tk.ttk.Labelframe))
    checkboxes = [w for w in panel.winfo_children() if isinstance(w, tk.ttk.Checkbutton)]
    assert len(checkboxes) == 2 and all(c.winfo_ismapped() for c in checkboxes)
    bottom = panel.winfo_rooty() + panel.winfo_height()
    assert bottom <= app.root.winfo_rooty() + app.root.winfo_height()
    status_bar = next(w for w in app.root.winfo_children()
                      if isinstance(w, tk.ttk.Label) and str(w.cget("textvariable")) == str(app.status))
    assert status_bar.winfo_ismapped()


def test_export_folder_setting(app, tmp_path):
    app.title.set("Airbus A320neo")
    app.import_mobiflight(PROJECT)
    app.wait_idle()
    assert app.project_info.get() == f"Project: {PROJECT}"
    app.build_mapping(False)
    app.wait_idle()
    custom = tmp_path / "my projects"
    app.set_export_folder(custom)
    app.wait_idle()
    assert app.export_folder.get() == str(custom)
    assert app.last_export.path.parent == custom and app.last_export.path.exists()
    app.set_export_folder(None)
    app.wait_idle()
    assert app.export_folder.get() == str(app.store.home / "mobiflight")


def test_earlier_import_is_shown_at_startup(tmp_path):
    from msfs_mapper.data import function_catalog
    from msfs_mapper.mobiflight import import_project

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    store = Store(tmp_path)
    store.save_mobiflight(import_project(PROJECT, function_catalog()))
    app = App(root, store, detect=lambda: [])
    try:
        assert len(app.mf_tree.get_children()) == 5
        assert app.project_info.get().startswith("Project:")
    finally:
        root.destroy()
        del app, root
        gc.collect()
