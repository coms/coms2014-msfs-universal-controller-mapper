import json

import pytest

from msfs_mapper.firmware_config import (
    DEFAULT_MOBIFLIGHT_CONFIG,
    load_mobiflight_config,
    save_mobiflight_config,
    write_arduino_header,
)


def test_default_config_and_generated_header(tmp_path):
    config_path = tmp_path / "mobiflight.json"
    assert load_mobiflight_config(config_path) == DEFAULT_MOBIFLIGHT_CONFIG

    saved_path = save_mobiflight_config(
        config_path,
        {"button_pins": [30, 31], "encoder_pins": [[2, 3]]},
    )
    assert json.loads(saved_path.read_text("utf-8")) == {
        "button_pins": [30, 31],
        "encoder_pins": [[2, 3]],
    }
    header_path = write_arduino_header(
        tmp_path / "mobiflight_config.h", load_mobiflight_config(config_path)
    )
    header = header_path.read_text("ascii")
    assert "buttonPins[] = {30, 31}" in header
    assert "encoderPins[][2] = {{2, 3}}" in header
    assert "BUTTON_COUNT = 2" in header
    assert "ENCODER_COUNT = 1" in header


@pytest.mark.parametrize(
    "config",
    [
        {"button_pins": [], "encoder_pins": []},
        {"button_pins": [2, 2], "encoder_pins": []},
        {"button_pins": [22], "encoder_pins": [[4, 5]]},
        {"button_pins": [2], "encoder_pins": [[2, 3]]},
        {"button_pins": [22], "encoder_pins": [[2]]},
    ],
)
def test_rejects_invalid_pin_assignments(config):
    from msfs_mapper.firmware_config import validate_mobiflight_config

    with pytest.raises(ValueError):
        validate_mobiflight_config(config)
