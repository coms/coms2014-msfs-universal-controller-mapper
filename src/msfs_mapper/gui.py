"""Small Tkinter interface for detecting hardware and generating aircraft mappings."""

from __future__ import annotations

from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk

from msfs_mapper.mapping.engine import functions_for
from msfs_mapper.firmware_config import (
    load_mobiflight_config,
    save_mobiflight_config,
)
from msfs_mapper.models import (
    AircraftInfo,
    AircraftProfile,
    ControllerSetup,
    DetectedDevice,
    MappingProfile,
)
from msfs_mapper.pipeline import Mapper
from msfs_mapper.profiles.store import Store

ENGINE_TYPES = {"Piston": 0, "Jet": 1, "Turboprop": 5}


def generate_mapping(
    mapper: Mapper,
    detected: list[DetectedDevice],
    aircraft: AircraftInfo,
) -> tuple[ControllerSetup, AircraftProfile, MappingProfile]:
    """Build a fresh mapping using the same pipeline as the CLI."""
    setup = mapper.setup(detected)
    profile = mapper.aircraft_profile(aircraft, refresh=True)
    mapping = mapper.mapping(setup, profile, refresh=True)
    return setup, profile, mapping


def launch_gui(home: Path | None = None, no_ai: bool = False) -> None:
    from msfs_mapper.ai import Claude
    from msfs_mapper.devices.discovery import PygameBackend

    mapper = Mapper(Store(home), None if no_ai else Claude())
    root = tk.Tk()
    root.title("MSFS Universal Controller Mapper")
    root.minsize(760, 560)

    container = ttk.Frame(root, padding=14)
    container.pack(fill="both", expand=True)
    container.columnconfigure(0, weight=1)

    ttk.Label(container, text="Aircraft", font=("Segoe UI", 14, "bold")).grid(
        row=0, column=0, sticky="w", pady=(0, 8)
    )
    form = ttk.Frame(container)
    form.grid(row=1, column=0, sticky="ew")
    form.columnconfigure(1, weight=1)
    ttk.Label(form, text="Aircraft title").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
    title_var = tk.StringVar()
    title_entry = ttk.Entry(form, textvariable=title_var)
    title_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)

    ttk.Label(form, text="Engine type").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
    engine_var = tk.StringVar(value="Piston")
    ttk.Combobox(
        form, textvariable=engine_var, values=list(ENGINE_TYPES), state="readonly", width=16
    ).grid(row=1, column=1, sticky="w", pady=4)
    ttk.Label(form, text="Engines").grid(row=1, column=2, sticky="e", padx=(14, 8), pady=4)
    engine_count = tk.IntVar(value=1)
    ttk.Spinbox(form, from_=1, to=4, textvariable=engine_count, width=5).grid(
        row=1, column=3, sticky="w", pady=4
    )
    retractable_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(form, text="Retractable landing gear", variable=retractable_var).grid(
        row=2, column=1, columnspan=3, sticky="w", pady=4
    )

    actions = ttk.Frame(container)
    actions.grid(row=2, column=0, sticky="ew", pady=(8, 10))
    status_var = tk.StringVar(value="Enter aircraft details, then detect devices and build a mapping.")
    ttk.Label(container, text="Detected controllers", font=("Segoe UI", 11, "bold")).grid(
        row=3, column=0, sticky="nw"
    )
    device_list = tk.Listbox(container, height=5, exportselection=False)
    device_list.grid(row=4, column=0, sticky="ew", pady=(4, 10))
    container.rowconfigure(5, weight=1)

    ttk.Label(container, text="Mapping", font=("Segoe UI", 11, "bold")).grid(
        row=5, column=0, sticky="nw"
    )
    mapping_table = ttk.Treeview(
        container, columns=("function", "device", "control"), show="headings", height=10
    )
    mapping_table.heading("function", text="Aircraft function")
    mapping_table.heading("device", text="Device")
    mapping_table.heading("control", text="Control")
    mapping_table.column("function", width=220)
    mapping_table.column("device", width=220)
    mapping_table.column("control", width=180)
    mapping_table.grid(row=6, column=0, sticky="nsew", pady=(4, 6))
    container.rowconfigure(6, weight=1)
    scrollbar = ttk.Scrollbar(container, orient="vertical", command=mapping_table.yview)
    scrollbar.grid(row=6, column=1, sticky="ns", pady=(4, 6))
    mapping_table.configure(yscrollcommand=scrollbar.set)
    ttk.Label(container, textvariable=status_var, wraplength=720).grid(
        row=7, column=0, sticky="ew", pady=(4, 0)
    )

    detected_devices: list[DetectedDevice] = []

    def detect_devices() -> None:
        nonlocal detected_devices
        try:
            detected_devices = PygameBackend().list_devices()
        except (ImportError, OSError, RuntimeError) as exc:
            messagebox.showerror("Device detection failed", str(exc), parent=root)
            return
        device_list.delete(0, tk.END)
        setup = mapper.setup(detected_devices)
        for device in setup.devices:
            definition = device.definition
            label = (
                f"{device.detected.name} — {definition.name} ({device.detected.usb_id})"
                if definition
                else f"{device.detected.name} — not in catalog ({device.detected.usb_id or 'unknown USB ID'})"
            )
            device_list.insert(tk.END, label)
        status_var.set(
            f"Found {len(detected_devices)} controller(s). "
            "Unknown devices need a catalog definition before they can be mapped."
        )

    def build_mapping() -> None:
        title = title_var.get().strip()
        if not title:
            messagebox.showerror("Aircraft required", "Enter the aircraft title.", parent=root)
            title_entry.focus_set()
            return
        if not detected_devices:
            detect_devices()
            if not detected_devices:
                return
        try:
            count = engine_count.get()
            if not 1 <= count <= 4:
                raise ValueError("Engine count must be between 1 and 4.")
            aircraft = AircraftInfo(
                title=title,
                engine_type=ENGINE_TYPES[engine_var.get()],
                engine_count=count,
                retractable_gear=retractable_var.get(),
            )
            setup, profile, mapping = generate_mapping(mapper, detected_devices, aircraft)
        except (ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror("Could not build mapping", str(exc), parent=root)
            return

        for item in mapping_table.get_children():
            mapping_table.delete(item)
        functions = functions_for(profile)
        names = {device.key: device.detected.name for device in setup.devices}
        for binding in mapping.bindings:
            mapping_table.insert(
                "",
                tk.END,
                values=(
                    functions[binding.function].name,
                    names.get(binding.device, binding.device),
                    binding.control,
                ),
            )
        suffix = (
            f" | Unassigned: {', '.join(mapping.unassigned_functions)}"
            if mapping.unassigned_functions
            else ""
        )
        status_var.set(
            f"{profile.aircraft.title} — {profile.template}; "
            f"{len(mapping.bindings)} binding(s), saved for this aircraft and device setup.{suffix}"
        )

    def configure_mega() -> None:
        config_path = mapper.store.home / "mobiflight_mega.json"
        try:
            config = load_mobiflight_config(config_path)
        except ValueError as exc:
            messagebox.showerror("Invalid Mega pin configuration", str(exc), parent=root)
            return
        dialog = tk.Toplevel(root)
        dialog.title("MobiFlight Mega pin configuration")
        dialog.transient(root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Button digital pins (comma-separated)").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        button_pins_var = tk.StringVar(
            value=", ".join(str(pin) for pin in config["button_pins"])
        )
        ttk.Entry(frame, textvariable=button_pins_var, width=52).grid(
            row=1, column=0, sticky="ew", pady=(0, 10)
        )
        ttk.Label(
            frame,
            text="Encoder interrupt pin pairs (one A,B pair per encoder; separate pairs with semicolons)",
        ).grid(row=2, column=0, sticky="w", pady=(0, 4))
        encoder_default = "; ".join(
            f"{pair[0]}, {pair[1]}" for pair in config["encoder_pins"]
        )
        encoder_pins_var = tk.StringVar(value=encoder_default)
        ttk.Entry(frame, textvariable=encoder_pins_var, width=52).grid(
            row=3, column=0, sticky="ew", pady=(0, 6)
        )
        ttk.Label(
            frame,
            text="Example: buttons 22,23,24; encoders 2,3; 18,19. Encoder pins must support interrupts.",
            wraplength=440,
        ).grid(row=4, column=0, sticky="w", pady=(0, 10))

        def save_config() -> None:
            try:
                buttons = [
                    int(pin.strip())
                    for pin in button_pins_var.get().split(",")
                    if pin.strip()
                ]
                encoders = [
                    [int(pin.strip()) for pin in pair.split(",")]
                    for pair in encoder_pins_var.get().split(";")
                    if pair.strip()
                ]
                saved = save_mobiflight_config(
                    config_path, {"button_pins": buttons, "encoder_pins": encoders}
                )
            except ValueError as exc:
                messagebox.showerror("Invalid pin configuration", str(exc), parent=dialog)
                return
            status_var.set(f"Mega pin configuration saved to {saved}")
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="e")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Save configuration", command=save_config).pack(
            side="right", padx=(0, 8)
        )

    ttk.Button(actions, text="Detect / refresh devices", command=detect_devices).pack(
        side="left", padx=(0, 8)
    )
    ttk.Button(actions, text="Build mapping", command=build_mapping).pack(side="left")
    ttk.Button(actions, text="Configure Mega pins", command=configure_mega).pack(
        side="left", padx=(8, 0)
    )
    detect_devices()
    root.mainloop()
