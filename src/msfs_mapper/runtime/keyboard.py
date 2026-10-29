"""Use a keyboard's rotary knob (volume roller, macro-pad encoder) as an encoder in the sim.

Such knobs are not game controllers: they send key presses, most often the media keys
Volume Up / Volume Down / Mute. While the bridge runs, a Windows low-level keyboard hook
catches those keys system-wide (MSFS has focus, not us), turns them into button events on a
virtual device, and, if the knob is mapped, swallows them so the system volume stays put.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from collections.abc import Callable, Iterator

from msfs_mapper.models import (
    ControlKind,
    DetectedDevice,
    DeviceDefinition,
    KeyboardKnob,
    PhysicalControl,
    SetupDevice,
)
from msfs_mapper.runtime.inputs import ButtonChanged

log = logging.getLogger(__name__)

KEYBOARD_INDEX = -1  # virtual device index; SDL joysticks are numbered from 0
INC, DEC, PRESS = 0, 1, 2  # virtual button numbers

# Windows virtual-key codes: (turn clockwise, turn counter-clockwise, press)
KEY_PRESETS: dict[str, tuple[str, tuple[int, int, int]]] = {
    "volume": ("Volume Up / Volume Down / Mute", (0xAF, 0xAE, 0xAD)),
    "media": ("Next track / Previous track / Play-Pause", (0xB0, 0xB1, 0xB3)),
    "f13": ("F13 / F14 / F15 (programmable knobs)", (0x7C, 0x7D, 0x7E)),
}

# Choice id -> (label, role the control gets). Ids are what the CLI accepts.
KNOB_ROLES: dict[str, tuple[str, str]] = {
    "auto": ("Automatic", "encoder"),
    "hdg": ("Heading bug", "encoder.hdg"),
    "alt": ("Selected altitude", "encoder.alt"),
    "vs": ("Selected vertical speed", "encoder.vs"),
    "trim": ("Elevator trim", "trim.pitch"),
    "flaps": ("Flaps", "flaps"),
}

PRESS_ROLES: dict[str, tuple[str, str | None]] = {
    "none": ("Nothing (keep Mute working)", None),
    "ap": ("Autopilot master", "autopilot.master"),
    "ap-disconnect": ("Autopilot disconnect", "autopilot.disconnect"),
    "hdg-mode": ("Heading mode", "autopilot.hdg"),
    "alt-hold": ("Altitude hold", "autopilot.alt"),
    "parking-brake": ("Parking brake", "parking_brake"),
}


def choice_for(choices: dict[str, tuple[str, str | None]], role: str | None) -> str:
    return next((cid for cid, (_, r) in choices.items() if r == role), next(iter(choices)))


def knob_device(config: KeyboardKnob) -> SetupDevice:
    controls = [
        PhysicalControl(id="knob", kind=ControlKind.ENCODER, label="Knob",
                        roles=[config.knob_role], inc_button=INC, dec_button=DEC, verified=True)
    ]
    if config.press_role:
        controls.append(PhysicalControl(id="knob_press", kind=ControlKind.BUTTON, label="Knob press",
                                        roles=[config.press_role], button=PRESS, verified=True))
    return SetupDevice(
        detected=DetectedDevice(index=KEYBOARD_INDEX, name=config.name),
        definition=DeviceDefinition(name=config.name, manufacturer="Keyboard", vendor_id=0,
                                    product_id=0, controls=controls),
        position="center",
    )


class KnobDecoder:
    """Turns key codes into virtual button events. Pure logic, shared by the hook and tests."""

    def __init__(self, config: KeyboardKnob):
        inc, dec, press = KEY_PRESETS[config.keys][1]
        self.buttons = {inc: INC, dec: DEC}
        if config.press_role:
            self.buttons[press] = PRESS

    def decode(self, vk: int, pressed: bool) -> ButtonChanged | None:
        button = self.buttons.get(vk)
        return None if button is None else ButtonChanged(KEYBOARD_INDEX, button, pressed)


class KeyboardKnobHook:
    """Windows low-level keyboard hook on its own thread. `capture(button)` decides, per key,
    whether the key is swallowed (the knob currently drives the sim) or passed on to Windows."""

    def __init__(self, config: KeyboardKnob, capture: Callable[[int], bool]):
        if sys.platform != "win32":
            raise OSError("the keyboard knob needs Windows (it hooks the Windows keyboard)")
        self.config = config
        self.decoder = KnobDecoder(config)
        self.capture = capture
        self.events: queue.Queue[ButtonChanged] = queue.Queue()
        self._thread_id = 0
        self._ready = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="keyboard-knob", daemon=True).start()
        self._ready.wait(5)

    def drain(self) -> Iterator[ButtonChanged]:
        while True:
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                return

    def stop(self) -> None:
        if self._thread_id:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        WH_KEYBOARD_LL = 13
        KEYDOWN = {0x0100, 0x0104}  # WM_KEYDOWN, WM_SYSKEYDOWN
        KEYUP = {0x0101, 0x0105}
        LLKHF_INJECTED = 0x10
        LRESULT = ctypes.c_ssize_t

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        hook = None

        def callback(code: int, wparam: int, lparam: int) -> int:
            # Must return fast: Windows drops hooks that stall the keyboard.
            if code == 0 and (wparam in KEYDOWN or wparam in KEYUP):
                info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not info.flags & LLKHF_INJECTED:
                    event = self.decoder.decode(info.vkCode, wparam in KEYDOWN)
                    if event is not None:
                        self.events.put(event)
                        if self.config.suppress and self.capture(event.button):
                            return 1
            return user32.CallNextHookEx(hook, code, wparam, lparam)

        proc = HOOKPROC(callback)  # keep a reference: a collected callback crashes the process
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, kernel32.GetModuleHandleW(None), 0)
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        if not hook:
            log.error("could not install the keyboard hook (error %s)", ctypes.get_last_error())
            return
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
        finally:
            user32.UnhookWindowsHookEx(hook)
