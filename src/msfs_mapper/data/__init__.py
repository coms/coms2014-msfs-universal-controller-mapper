"""Bundled catalogs: sim functions, checklist templates and known controller devices."""

from __future__ import annotations

from functools import cache
from importlib import resources
from typing import Any

import yaml

from msfs_mapper.models import SimFunction


def load_yaml(*parts: str) -> Any:
    return yaml.safe_load(resources.files(__package__).joinpath(*parts).read_text("utf-8"))


def list_yaml(folder: str) -> list[Any]:
    root = resources.files(__package__).joinpath(folder)
    return [
        yaml.safe_load(entry.read_text("utf-8"))
        for entry in sorted(root.iterdir(), key=lambda e: e.name)
        if entry.name.endswith(".yaml")
    ]


def _action(raw: Any) -> dict[str, str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return {"type": "event", "value": raw}
    return {"type": "calculator", "value": raw["calc"]}


@cache
def function_catalog() -> dict[str, SimFunction]:
    functions = {}
    for raw in load_yaml("functions.yaml"):
        # YAML 1.1 reads bare `on:` / `off:` keys as booleans.
        raw["actions"] = {
            {True: "on", False: "off"}.get(kind, kind): _action(value)
            for kind, value in raw["actions"].items()
        }
        fn = SimFunction.model_validate(raw)
        functions[fn.id] = fn
    return functions
