from msfs_mapper import cli

from conftest import ALPHA, BRAVO, PEDALS


def test_map_command_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_detect", lambda: [ALPHA, BRAVO, PEDALS])
    args = ["--home", str(tmp_path), "--no-ai", "map", "--title", "Beechcraft Bonanza G36",
            "--engine-type", "0", "--retractable"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "Landing gear" in out and "gear_lever" in out
    assert list((tmp_path / "mappings").glob("beechcraft-bonanza-g36__*.json"))


def test_gui_mapping_preview_uses_detected_devices_and_persists_mapping(tmp_path):
    from msfs_mapper.gui import generate_mapping
    from msfs_mapper.models import AircraftInfo
    from msfs_mapper.pipeline import Mapper
    from msfs_mapper.profiles.store import Store

    aircraft = AircraftInfo(
        title="Cessna Skyhawk",
        engine_type=0,
        engine_count=1,
        retractable_gear=True,
    )
    setup, profile, mapping = generate_mapping(
        Mapper(Store(tmp_path)),
        [ALPHA, BRAVO, PEDALS],
        aircraft,
    )

    assert profile.aircraft.title == aircraft.title
    assert any(binding.control == "gear_lever" for binding in mapping.bindings)
    assert setup.fingerprint() == mapping.setup_fingerprint
    assert list((tmp_path / "mappings").glob("cessna-skyhawk__*.json"))
