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
