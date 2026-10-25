"""Read the loaded aircraft from the sim over SimConnect."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

from msfs_mapper.models import AircraftInfo


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").rstrip("\x00")
    return "" if value is None else str(value)


class SimConnectAircraftSource:
    """Polls aircraft simulation variables. Requires `pip install msfs-mapper[sim]` and a running sim."""

    def __init__(self, sim: Any | None = None):
        if sim is None:
            from SimConnect import SimConnect  # optional dependency

            sim = SimConnect()
        from SimConnect import AircraftRequests

        self.sim = sim
        self.requests = AircraftRequests(sim, _time=1000)

    def read(self) -> AircraftInfo | None:
        title = _text(self.requests.get("TITLE"))
        if not title:
            return None

        def number(name: str) -> int | None:
            value = self.requests.get(name)
            return None if value is None else int(value)

        return AircraftInfo(
            title=title,
            atc_model=_text(self.requests.get("ATC_MODEL")),
            atc_type=_text(self.requests.get("ATC_TYPE")),
            category=_text(self.requests.get("CATEGORY")),
            engine_type=number("ENGINE_TYPE"),
            engine_count=number("NUMBER_OF_ENGINES") or 1,
            retractable_gear=bool(number("IS_GEAR_RETRACTABLE")),
            flaps_positions=number("FLAPS_NUM_HANDLE_POSITIONS") or 0,
        )


def watch_aircraft(
    read: Callable[[], AircraftInfo | None], interval: float = 3.0
) -> Iterator[AircraftInfo]:
    """Yield an AircraftInfo every time a different aircraft is loaded."""
    current = None
    while True:
        info = read()
        if info and info.title != current:
            current = info.title
            yield info
        time.sleep(interval)
