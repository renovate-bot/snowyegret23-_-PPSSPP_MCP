from __future__ import annotations

import ctypes
import threading
import time
from typing import Any

from .background_input import normalize_button


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterWindowMessageW.argtypes = [ctypes.c_wchar_p]
user32.RegisterWindowMessageW.restype = ctypes.c_uint
user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.PostMessageW.restype = ctypes.c_bool

BACKGROUND_KEY_MESSAGE = user32.RegisterWindowMessageW("PPSSPP.MCP.BackgroundKey")

_BUTTON_KEYS = {
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "square": ord("A"),
    "triangle": ord("S"),
    "circle": ord("X"),
    "cross": ord("Z"),
    "ltrigger": ord("Q"),
    "rtrigger": ord("W"),
    "start": 0x20,
    "select": ord("V"),
}


def _post_key(hwnd: int, virtual_key: int, pressed: bool) -> None:
    if not BACKGROUND_KEY_MESSAGE:
        raise OSError(ctypes.get_last_error(), "RegisterWindowMessageW failed")
    if not user32.PostMessageW(
        ctypes.c_void_p(hwnd),
        BACKGROUND_KEY_MESSAGE,
        virtual_key,
        1 if pressed else 0,
    ):
        raise OSError(ctypes.get_last_error(), f"PostMessageW failed for 0x{hwnd:X}")


class BackgroundKeyboard:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._held: dict[tuple[int, str], int] = {}

    def press(self, hwnd: int, button: str, duration_ms: int) -> dict[str, Any]:
        name = normalize_button(button)
        if not 1 <= duration_ms <= 10_000:
            raise ValueError("duration_ms must be between 1 and 10000")
        virtual_key = _BUTTON_KEYS[name]
        held_key = (hwnd, name)
        with self._lock:
            was_held = held_key in self._held
            if not was_held:
                _post_key(hwnd, virtual_key, True)
            try:
                time.sleep(duration_ms / 1000.0)
            finally:
                if not was_held:
                    _post_key(hwnd, virtual_key, False)
            return {
                "backend": "keyboard/PPSSPP.MCP.BackgroundKey",
                "button": name,
                "virtual_key": f"0x{virtual_key:02X}",
                "duration_ms": duration_ms,
                "hwnd": f"0x{hwnd:X}",
                "foreground_activation": False,
            }

    def set_buttons(self, hwnd: int, buttons: dict[str, bool | None]) -> dict[str, Any]:
        updates: list[tuple[str, bool, int]] = []
        for button, pressed in buttons.items():
            name = normalize_button(button)
            if pressed is None:
                continue
            if not isinstance(pressed, bool):
                raise ValueError(f"button state for {button!r} must be true, false, or null")
            updates.append((name, pressed, _BUTTON_KEYS[name]))
        with self._lock:
            for name, pressed, virtual_key in updates:
                held_key = (hwnd, name)
                if pressed and held_key not in self._held:
                    _post_key(hwnd, virtual_key, True)
                    self._held[held_key] = virtual_key
                elif not pressed and held_key in self._held:
                    _post_key(hwnd, self._held.pop(held_key), False)
            return {
                "backend": "keyboard/PPSSPP.MCP.BackgroundKey",
                "hwnd": f"0x{hwnd:X}",
                "held": sorted(name for held_hwnd, name in self._held if held_hwnd == hwnd),
                "foreground_activation": False,
            }

    def set_analog(self, hwnd: int, x: float, y: float, stick: str) -> dict[str, Any]:
        side = stick.strip().lower()
        if side != "left":
            raise ValueError("the default PPSSPP keyboard map only provides the left analog stick")
        if not -1.0 <= x <= 1.0 or not -1.0 <= y <= 1.0:
            raise ValueError("x and y must be between -1.0 and 1.0")
        states = {
            "analog_left": (ord("J"), x < -0.25),
            "analog_right": (ord("L"), x > 0.25),
            "analog_up": (ord("I"), y > 0.25),
            "analog_down": (ord("K"), y < -0.25),
        }
        with self._lock:
            for name, (virtual_key, pressed) in states.items():
                held_key = (hwnd, name)
                if pressed and held_key not in self._held:
                    _post_key(hwnd, virtual_key, True)
                    self._held[held_key] = virtual_key
                elif not pressed and held_key in self._held:
                    _post_key(hwnd, self._held.pop(held_key), False)
            return {
                "backend": "keyboard/PPSSPP.MCP.BackgroundKey",
                "hwnd": f"0x{hwnd:X}",
                "stick": side,
                "x": x,
                "y": y,
                "foreground_activation": False,
            }

    def reset(self, hwnd: int) -> dict[str, Any]:
        with self._lock:
            released = []
            for held_key, virtual_key in list(self._held.items()):
                held_hwnd, name = held_key
                if held_hwnd != hwnd:
                    continue
                _post_key(hwnd, virtual_key, False)
                self._held.pop(held_key, None)
                released.append(name)
            return {
                "backend": "keyboard/PPSSPP.MCP.BackgroundKey",
                "hwnd": f"0x{hwnd:X}",
                "released": sorted(released),
                "foreground_activation": False,
            }


keyboard = BackgroundKeyboard()
