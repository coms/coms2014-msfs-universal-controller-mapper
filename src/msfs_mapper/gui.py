"""Desktop window: hardware, MobiFlight import, aircraft and the resulting mapping in one place.

Built on tkinter, which ships with Python on Windows, so the GUI needs no extra install.
Slow work (USB scan, SimConnect, Claude calls) runs on a worker thread; results come back to
the Tk thread through a queue polled with `after`, because Tk widgets are not thread-safe.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import anthropic

from msfs_mapper.ai import AIError, Claude
from msfs_mapper.data import function_catalog
from msfs_mapper.mapping.engine import functions_for
from msfs_mapper.mobiflight import MobiFlightError
from msfs_mapper.models import (
    AircraftInfo,
    AircraftProfile,
    ControllerSetup,
    DetectedDevice,
    KeyboardKnob,
    MappingProfile,
    MobiFlightImport,
)
from msfs_mapper.pipeline import Mapper
from msfs_mapper.profiles.store import Store
from msfs_mapper.runtime.keyboard import KEY_PRESETS, KEYBOARD_INDEX, KNOB_ROLES, PRESS_ROLES, choice_for

log = logging.getLogger(__name__)

ENGINE_TYPES = {"Piston": 0, "Jet": 1, "Turboprop": 5}
NOT_RECOGNISED = "(not recognised)"


def detect_usb() -> list[DetectedDevice]:
    from msfs_mapper.devices.discovery import PygameBackend  # needs pygame (msfs-mapper[sim])

    return PygameBackend().list_devices()


class App:
    def __init__(
        self,
        root: tk.Tk,
        store: Store,
        detect: Callable[[], list[DetectedDevice]] = detect_usb,
        claude_factory: Callable[[], Claude] = Claude,
    ):
        self.root = root
        self.store = store
        self.detect = detect
        self.claude_factory = claude_factory
        self.detected: list[DetectedDevice] = []
        self.setup = ControllerSetup()
        self.profile: AircraftProfile | None = None
        self.mapping: MappingProfile | None = None
        self._sim_aircraft: AircraftInfo | None = None
        self._results: queue.Queue[Callable[[], None]] = queue.Queue()
        self._busy = 0

        root.title("MSFS Controller Mapper")
        root.geometry("1000x700")
        root.minsize(760, 520)
        self.use_ai = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Ready")
        self._build()
        root.after(100, self._poll)
        self.refresh_devices()

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", **pad)
        ttk.Button(bar, text="Refresh devices", command=self.refresh_devices).pack(side="left")
        ttk.Button(bar, text="Scan setup photo…", command=self.ask_photo).pack(side="left", padx=4)
        ttk.Button(bar, text="Import MobiFlight project…", command=self.ask_mobiflight).pack(side="left")
        ttk.Button(bar, text="Clear MobiFlight", command=self.clear_mobiflight).pack(side="left", padx=4)
        ttk.Button(bar, text="Keyboard knob…", command=self.open_knob_dialog).pack(side="left")
        ttk.Checkbutton(bar, text="Use Claude AI", variable=self.use_ai).pack(side="right")

        hardware = ttk.LabelFrame(self.root, text="Hardware")
        hardware.pack(fill="x", **pad)
        self.devices = self._tree(
            hardware, ("name", "kind", "id", "catalog", "position", "controls"),
            ("Device", "Connected via", "ID", "Recognised as", "Position", "Controls"), height=6,
            widths=(220, 100, 110, 220, 80, 160),
        )

        aircraft = ttk.LabelFrame(self.root, text="Aircraft")
        aircraft.pack(fill="x", **pad)
        self.title = tk.StringVar()
        self.engine = tk.StringVar(value="Piston")
        self.engines = tk.IntVar(value=1)
        self.retractable = tk.BooleanVar()
        ttk.Label(aircraft, text="Title").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(aircraft, textvariable=self.title, width=36).grid(row=0, column=1, sticky="we")
        ttk.Label(aircraft, text="Engine").grid(row=0, column=2, padx=(12, 4))
        ttk.Combobox(aircraft, textvariable=self.engine, values=list(ENGINE_TYPES), width=10,
                     state="readonly").grid(row=0, column=3)
        ttk.Label(aircraft, text="Engines").grid(row=0, column=4, padx=(12, 4))
        ttk.Spinbox(aircraft, from_=1, to=4, textvariable=self.engines, width=3).grid(row=0, column=5)
        ttk.Checkbutton(aircraft, text="Retractable gear", variable=self.retractable).grid(
            row=0, column=6, padx=12)
        buttons = ttk.Frame(aircraft)
        buttons.grid(row=1, column=0, columnspan=7, sticky="w", padx=4, pady=(0, 6))
        ttk.Button(buttons, text="Read from sim", command=self.read_from_sim).pack(side="left")
        ttk.Button(buttons, text="Build mapping", command=lambda: self.build_mapping(False)).pack(
            side="left", padx=4)
        ttk.Button(buttons, text="Rebuild", command=lambda: self.build_mapping(True)).pack(side="left")
        aircraft.columnconfigure(1, weight=1)

        tabs = ttk.Notebook(self.root)
        tabs.pack(fill="both", expand=True, **pad)
        mapping_tab = ttk.Frame(tabs)
        tabs.add(mapping_tab, text="Mapping")
        self.mapping_tree = self._tree(
            mapping_tab, ("function", "device", "control", "source"),
            ("Function", "Assigned to", "Control", "Source"),
        )
        ttk.Button(mapping_tab, text="Lock / unlock selected", command=self.toggle_lock).pack(
            anchor="w", pady=4)

        mf_tab = ttk.Frame(tabs)
        tabs.add(mf_tab, text="MobiFlight inputs")
        self.mf_tree = self._tree(
            mf_tab, ("module", "input", "type", "description", "function", "command"),
            ("Panel", "Input", "Type", "Description", "Function", "Command"),
        )
        self.mf_tree.bind("<Double-1>", lambda _e: self.edit_mobiflight_function())
        ttk.Label(mf_tab, text="Double-click an input to set which function it operates.").pack(
            anchor="w", pady=4)
        self.tabs = tabs

        ttk.Label(self.root, textvariable=self.status, relief="sunken", anchor="w").pack(
            fill="x", side="bottom")

    def _tree(
        self, parent: tk.Widget, columns: tuple, headings: tuple, height: int = 10,
        widths: tuple | None = None,
    ) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=4, pady=4)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
        for i, (column, heading) in enumerate(zip(columns, headings)):
            tree.heading(column, text=heading)
            tree.column(column, width=widths[i] if widths else 120, stretch=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    # --------------------------------------------------------------- threading

    def run_task(self, label: str, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run `work` on a worker thread, then `done(result)` on the Tk thread."""
        self._busy += 1
        self.status.set(f"{label}…")

        def worker() -> None:
            try:
                result = work()
                self._results.put(lambda: done(result))
            except Exception as exc:  # noqa: BLE001 - every failure must reach the user, not a dead thread
                log.exception("%s failed", label)
                self._results.put(lambda exc=exc: self._fail(label, exc))
            finally:
                self._results.put(self._task_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _task_finished(self) -> None:
        self._busy -= 1

    def _fail(self, label: str, exc: Exception) -> None:
        self.status.set(f"{label} failed: {exc}")
        self.alert(f"{label} failed:\n\n{exc}", error=True)

    def alert(self, text: str, error: bool = False) -> None:
        show = messagebox.showerror if error else messagebox.showinfo
        show("MSFS Controller Mapper", text, parent=self.root)

    def _poll(self) -> None:
        try:
            while True:
                try:
                    callback = self._results.get_nowait()
                except queue.Empty:
                    break
                try:
                    callback()
                except Exception:  # noqa: BLE001 - one bad result must not stop the poll loop
                    log.exception("updating the window failed")
        finally:
            self.root.after(100, self._poll)

    def wait_idle(self, timeout: float = 10.0) -> None:
        """Pump events until background tasks are finished (used by tests and scripts)."""
        import time

        deadline = time.monotonic() + timeout
        while (self._busy or not self._results.empty()) and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()

    def mapper(self) -> Mapper:
        claude = None
        if self.use_ai.get():
            try:
                claude = self.claude_factory()
            except anthropic.AnthropicError as exc:
                log.warning("Claude unavailable, continuing without AI: %s", exc)
        return Mapper(self.store, claude)

    # ----------------------------------------------------------------- devices

    def refresh_devices(self) -> None:
        def work() -> tuple[list[DetectedDevice], str]:
            try:
                return self.detect(), ""
            except ImportError:
                return [], "USB scan needs pygame: pip install msfs-mapper[sim]"

        def done(result: tuple[list[DetectedDevice], str]) -> None:
            self.detected, problem = result
            self.setup = self.mapper().setup(self.detected)
            self.show_devices()
            self.status.set(problem or f"{len(self.detected)} USB controller(s) found")

        self.run_task("Scanning USB controllers", work, done)

    def show_devices(self) -> None:
        self.devices.delete(*self.devices.get_children())
        for d in self.setup.devices:
            if d.detected.index == KEYBOARD_INDEX:
                self.devices.insert("", "end", values=(
                    d.detected.name, "Keyboard keys", KEY_PRESETS[self.store.load_keyboard().keys][0],
                    "Rotary knob", d.position, f"{len(d.controls)} controls"))
                continue
            catalog = f"{d.definition.manufacturer} {d.definition.name}".strip() if d.definition else "unknown"
            verified = sum(c.verified for c in d.controls)
            self.devices.insert("", "end", values=(
                d.detected.name, "USB", d.detected.usb_id or "?", catalog, d.position,
                f"{verified}/{len(d.controls)} verified"))
        imported = self.store.load_mobiflight()
        modules: dict[str, list] = {}
        for b in imported.bindings if imported else []:
            if "JS-" not in b.serial:  # MobiFlight joystick inputs are USB devices already listed
                modules.setdefault(b.module, []).append(b)
        for module, inputs in modules.items():
            handled = sum(1 for b in inputs if b.function)
            serial = inputs[0].serial.split("/", 1)[-1].strip()
            self.devices.insert("", "end", values=(
                module, "MobiFlight", serial, "MobiFlight panel", "-",
                f"{len(inputs)} inputs, {handled} recognised"))

    def ask_photo(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="Photo of your controller setup",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp"), ("All files", "*.*")])
        if path:
            self.scan_photo(Path(path))

    def scan_photo(self, photo: Path) -> None:
        mapper = self.mapper()

        def done(result: tuple[ControllerSetup, list[str]]) -> None:
            self.setup, messages = result
            self.show_devices()
            self.status.set("Setup photo analysed")
            if messages:
                self.alert("\n".join(messages))

        self.run_task("Analysing setup photo", lambda: mapper.scan_photo(photo, self.detected), done)

    # ----------------------------------------------------------- keyboard knob

    def open_knob_dialog(self) -> None:
        knob = self.store.load_keyboard()
        dialog = tk.Toplevel(self.root)
        dialog.title("Keyboard knob")
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)

        enabled = tk.BooleanVar(value=knob.enabled)
        keys = tk.StringVar(value=KEY_PRESETS[knob.keys][0])
        drives = tk.StringVar(value=KNOB_ROLES[choice_for(KNOB_ROLES, knob.knob_role)][0])
        press = tk.StringVar(value=PRESS_ROLES[choice_for(PRESS_ROLES, knob.press_role)][0])
        suppress = tk.BooleanVar(value=knob.suppress)

        ttk.Checkbutton(frame, text="Use the rotary knob on my keyboard", variable=enabled).grid(
            row=0, column=0, columnspan=2, sticky="w")
        for row, (label, var, values) in enumerate([
            ("Knob sends", keys, [label for label, _ in KEY_PRESETS.values()]),
            ("Turning drives", drives, [label for label, _ in KNOB_ROLES.values()]),
            ("Pressing does", press, [label for label, _ in PRESS_ROLES.values()]),
        ], start=1):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Combobox(frame, textvariable=var, values=values, state="readonly", width=38).grid(
                row=row, column=1, sticky="we", padx=(8, 0))
        ttk.Checkbutton(frame, text="Stop Windows changing the volume while the knob flies the plane",
                        variable=suppress).grid(row=4, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(frame, foreground="gray", wraplength=420, text=(
            "Most volume knobs send Volume Up / Down / Mute. If your keyboard software lets you "
            "reprogram the knob, F13 / F14 / F15 keeps it separate from your media keys. "
            "The knob is read while `msfs-mapper run` is running (Windows only).")).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(4, 8))

        def by_label(choices: dict, label: str) -> str:
            return next(cid for cid, (text, *_) in choices.items() if text == label)

        def save() -> None:
            self.save_knob(KeyboardKnob(
                enabled=enabled.get(),
                keys=by_label(KEY_PRESETS, keys.get()),
                knob_role=KNOB_ROLES[by_label(KNOB_ROLES, drives.get())][1],
                press_role=PRESS_ROLES[by_label(PRESS_ROLES, press.get())][1],
                suppress=suppress.get(),
            ))
            dialog.destroy()

        ttk.Button(frame, text="Save", command=save).grid(row=6, column=1, sticky="e")

    def save_knob(self, knob: KeyboardKnob) -> None:
        self.store.save_keyboard(knob)
        self.setup = self.mapper().setup(self.detected)
        self.show_devices()
        self.status.set(f"Keyboard knob {'enabled' if knob.enabled else 'disabled'}")
        if self.profile:
            self.build_mapping(False)

    # -------------------------------------------------------------- MobiFlight

    def ask_mobiflight(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="MobiFlight Connector project",
            filetypes=[("MobiFlight project", "*.mcc"), ("All files", "*.*")])
        if path:
            self.import_mobiflight(Path(path))

    def import_mobiflight(self, path: Path) -> None:
        mapper = self.mapper()

        def work() -> MobiFlightImport:
            try:
                return mapper.import_mobiflight(path, self.setup, self.profile)
            except (MobiFlightError, OSError) as exc:
                raise MobiFlightError(f"{path.name}: {exc}") from exc

        def done(imported: MobiFlightImport) -> None:
            self.show_mobiflight()
            self.show_devices()
            self.tabs.select(1)
            handled = imported.handled_functions()
            self.status.set(
                f"Imported {len(imported.bindings)} MobiFlight inputs; "
                f"{len(handled)} functions left to MobiFlight")
            if self.profile:
                self.build_mapping(False)

        self.run_task(f"Importing {path.name}", work, done)

    def clear_mobiflight(self) -> None:
        self.store.clear_mobiflight()
        self.show_mobiflight()
        self.show_devices()
        self.status.set("MobiFlight import cleared")
        if self.profile:
            self.build_mapping(False)

    def show_mobiflight(self) -> None:
        self.mf_tree.delete(*self.mf_tree.get_children())
        imported = self.store.load_mobiflight()
        names = {fid: f.name for fid, f in self._functions().items()}
        for i, b in enumerate(imported.bindings if imported else []):
            function = names.get(b.function, b.function) if b.function else NOT_RECOGNISED
            self.mf_tree.insert("", "end", iid=str(i), values=(
                b.module, b.input, b.input_type, b.description, function, "; ".join(b.commands)))

    def edit_mobiflight_function(self) -> None:
        imported = self.store.load_mobiflight()
        selection = self.mf_tree.selection()
        if not imported or not selection:
            return
        index = int(selection[0])
        binding = imported.bindings[index]
        functions = self._functions()
        choices = [NOT_RECOGNISED] + sorted(f.name for f in functions.values())
        by_name = {f.name: fid for fid, f in functions.items()}

        dialog = tk.Toplevel(self.root)
        dialog.title("MobiFlight input")
        dialog.transient(self.root)
        ttk.Label(dialog, text=f"{binding.module} / {binding.input}\nWhich function does it operate?").pack(
            padx=12, pady=8, anchor="w")
        current = functions[binding.function].name if binding.function in functions else NOT_RECOGNISED
        choice = tk.StringVar(value=current)
        ttk.Combobox(dialog, textvariable=choice, values=choices, state="readonly", width=40).pack(padx=12)

        def save() -> None:
            self.set_mobiflight_function(index, by_name.get(choice.get()))
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).pack(pady=8)

    def set_mobiflight_function(self, index: int, function: str | None) -> None:
        imported = self.store.load_mobiflight()
        if imported is None:
            return
        bindings = list(imported.bindings)
        bindings[index] = bindings[index].model_copy(update={"function": function})
        self.store.save_mobiflight(imported.model_copy(update={"bindings": bindings}))
        self.show_mobiflight()
        self.show_devices()
        if self.profile:
            self.build_mapping(False)

    # ---------------------------------------------------------------- aircraft

    def read_from_sim(self) -> None:
        def work() -> AircraftInfo | None:
            from msfs_mapper.aircraft.detect import SimConnectAircraftSource

            return SimConnectAircraftSource().read()

        def done(info: AircraftInfo | None) -> None:
            if info is None:
                self.status.set("No aircraft loaded in the sim")
                return
            self.title.set(info.title)
            engine = next((n for n, v in ENGINE_TYPES.items() if v == info.engine_type), "Piston")
            self.engine.set(engine)
            self.engines.set(info.engine_count)
            self.retractable.set(info.retractable_gear)
            self._sim_aircraft = info
            self.build_mapping(False)

        self.run_task("Reading aircraft from the sim", work, done)

    def aircraft_info(self) -> AircraftInfo:
        sim = self._sim_aircraft
        if sim is not None and sim.title == self.title.get().strip():
            return sim
        return AircraftInfo(
            title=self.title.get().strip(),
            engine_type=ENGINE_TYPES[self.engine.get()],
            engine_count=int(self.engines.get()),
            retractable_gear=self.retractable.get(),
        )

    def build_mapping(self, refresh: bool) -> None:
        if not self.title.get().strip():
            self.status.set("Enter an aircraft title or read it from the sim")
            return
        mapper, info, setup = self.mapper(), self.aircraft_info(), self.setup

        def work() -> tuple[AircraftProfile, MappingProfile]:
            profile = mapper.aircraft_profile(info, refresh=refresh)
            return profile, mapper.mapping(setup, profile, refresh=refresh)

        def done(result: tuple[AircraftProfile, MappingProfile]) -> None:
            self.profile, self.mapping = result
            self.show_mapping()
            self.show_mobiflight()
            self.tabs.select(0)
            self.status.set(
                f"{info.title}: {len(self.mapping.bindings)} controls mapped "
                f"({'with AI' if self.mapping.source == 'ai' else 'automatically'}), "
                f"{len(self.mapping.external)} left to MobiFlight, "
                f"{len(self.mapping.unassigned_functions)} without a control")

        self.run_task(f"Mapping {info.title}", work, done)

    def show_mapping(self) -> None:
        tree = self.mapping_tree
        tree.delete(*tree.get_children())
        if not (self.profile and self.mapping):
            return
        functions = self._functions()
        names = {d.key: d.detected.name for d in self.setup.devices}

        def name(fid: str) -> str:
            return functions[fid].name if fid in functions else fid

        for i, b in enumerate(self.mapping.bindings):
            source = "locked" if b.locked else {"ai": "AI", "heuristic": "auto"}.get(self.mapping.source, "user")
            tree.insert("", "end", iid=f"b{i}", values=(
                name(b.function), names.get(b.device, b.device), b.control, source))
        for b in self.mapping.external:
            tree.insert("", "end", values=(name(b.function), b.module, b.input, "MobiFlight"))
        for fid in self.mapping.unassigned_functions:
            tree.insert("", "end", values=(name(fid), "— no free control —", "", ""))

    def toggle_lock(self) -> None:
        if not self.mapping:
            return
        for iid in self.mapping_tree.selection():
            if iid.startswith("b"):
                binding = self.mapping.bindings[int(iid[1:])]
                binding.locked = not binding.locked
        self.store.save_mapping(self.mapping)
        self.show_mapping()
        self.status.set("Locked bindings are kept when the mapping is rebuilt")

    def _functions(self) -> dict:
        return functions_for(self.profile) if self.profile else function_catalog()


def run(home: Path | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = tk.Tk()
    App(root, Store(home))
    root.mainloop()
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
