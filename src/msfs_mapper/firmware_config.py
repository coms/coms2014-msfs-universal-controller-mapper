"""Load MobiFlight Mega pin configuration and generate its Arduino header."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_MOBIFLIGHT_CONFIG = {
    "button_pins": [22, 23, 24, 25, 26, 27, 28, 29],
    "encoder_pins": [[2, 3], [18, 19]],
}
MEGA_DIGITAL_PINS = set(range(2, 54))
MEGA_INTERRUPT_PINS = {2, 3, 18, 19, 20, 21}


def validate_mobiflight_config(config: dict) -> dict:
    """Validate and normalize button pin numbers and encoder pin pairs."""
    buttons = config.get("button_pins")
    encoders = config.get("encoder_pins")
    if not isinstance(buttons, list) or not 1 <= len(buttons) <= 32:
        raise ValueError("button_pins must contain between 1 and 32 Mega pins")
    if not isinstance(encoders, list) or len(encoders) > 3:
        raise ValueError("encoder_pins must contain between 0 and 3 pin pairs")
    if any(type(pin) is not int or pin not in MEGA_DIGITAL_PINS for pin in buttons):
        raise ValueError("button pins must be Arduino Mega digital pins 2 through 53")
    normalized_encoders = []
    for pair in encoders:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(type(pin) is not int or pin not in MEGA_INTERRUPT_PINS for pin in pair)
            or pair[0] == pair[1]
        ):
            raise ValueError("each encoder needs two distinct interrupt pins from 2, 3, 18, 19, 20, 21")
        normalized_encoders.append(list(pair))
    pins = buttons + [pin for pair in normalized_encoders for pin in pair]
    if len(pins) != len(set(pins)):
        raise ValueError("each physical pin can be assigned only once")
    return {"button_pins": list(buttons), "encoder_pins": normalized_encoders}


def load_mobiflight_config(path: Path) -> dict:
    if not path.exists():
        return validate_mobiflight_config(DEFAULT_MOBIFLIGHT_CONFIG)
    try:
        config = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("MobiFlight configuration must be a JSON object")
    return validate_mobiflight_config(config)


def save_mobiflight_config(path: Path, config: dict) -> Path:
    validated = validate_mobiflight_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(validated, indent=2) + "\n", "utf-8")
    return path


def write_arduino_header(path: Path, config: dict) -> Path:
    config = validate_mobiflight_config(config)
    buttons = ", ".join(str(pin) for pin in config["button_pins"])
    encoders = config["encoder_pins"] or [[2, 3]]
    encoder_rows = ", ".join("{" + ", ".join(map(str, pair)) + "}" for pair in encoders)
    header = (
        "#pragma once\n"
        "#include <Arduino.h>\n"
        f"const uint8_t buttonPins[] = {{{buttons}}};\n"
        f"const uint8_t encoderPins[][2] = {{{encoder_rows}}};\n"
        f"const uint8_t BUTTON_COUNT = {len(config['button_pins'])};\n"
        f"const uint8_t ENCODER_COUNT = {len(config['encoder_pins'])};\n"
    )
    path.write_text(header, "ascii")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="MobiFlight pin configuration JSON")
    parser.add_argument("--write-header", type=Path, required=True)
    args = parser.parse_args()
    if not args.config.exists():
        save_mobiflight_config(args.config, DEFAULT_MOBIFLIGHT_CONFIG)
    write_arduino_header(args.write_header, load_mobiflight_config(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
