from __future__ import annotations

from types import SimpleNamespace

import pytest

from msfs_mapper.ai import Claude
from msfs_mapper.devices.catalog import DeviceCatalog
from msfs_mapper.devices.discovery import build_setup
from msfs_mapper.models import DetectedDevice

ALPHA = DetectedDevice(index=0, name="Alpha Flight Controls", vendor_id=0x294B, product_id=0x1900, num_axes=2, num_buttons=35)
BRAVO = DetectedDevice(index=1, name="Bravo Throttle Quadrant", vendor_id=0x294B, product_id=0x1901, num_axes=7, num_buttons=48)
PEDALS = DetectedDevice(index=2, name="Saitek Pro Flight Rudder Pedals", vendor_id=0x06A3, product_id=0x0763, num_axes=3)
UNKNOWN = DetectedDevice(index=3, name="Generic USB Button Box", vendor_id=0x1234, product_id=0x0001, num_axes=0, num_buttons=12)


@pytest.fixture
def setup(tmp_path):
    return build_setup([ALPHA, BRAVO, PEDALS], DeviceCatalog(tmp_path / "devices"))


class FakeMessages:
    """Stands in for client.beta.messages: returns queued parsed outputs and records calls."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(stop_reason="end_turn", parsed_output=output)


def fake_claude(*outputs) -> tuple[Claude, FakeMessages]:
    messages = FakeMessages(outputs)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return Claude(client=client), messages
