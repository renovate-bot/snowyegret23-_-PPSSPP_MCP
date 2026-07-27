from __future__ import annotations

import atexit
import importlib
import importlib.util
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any


class BackgroundInputError(RuntimeError):
    pass


_BUTTON_ATTRIBUTES = {
    "up": "XUSB_GAMEPAD_DPAD_UP",
    "down": "XUSB_GAMEPAD_DPAD_DOWN",
    "left": "XUSB_GAMEPAD_DPAD_LEFT",
    "right": "XUSB_GAMEPAD_DPAD_RIGHT",
    "start": "XUSB_GAMEPAD_START",
    "select": "XUSB_GAMEPAD_BACK",
    "ltrigger": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "rtrigger": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "cross": "XUSB_GAMEPAD_A",
    "circle": "XUSB_GAMEPAD_B",
    "square": "XUSB_GAMEPAD_X",
    "triangle": "XUSB_GAMEPAD_Y",
}


def normalize_button(button: str) -> str:
    normalized = button.strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "a": "cross",
        "b": "circle",
        "x": "square",
        "y": "triangle",
        "back": "select",
        "l": "ltrigger",
        "l1": "ltrigger",
        "r": "rtrigger",
        "r1": "rtrigger",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in _BUTTON_ATTRIBUTES:
        valid = ", ".join(sorted(_BUTTON_ATTRIBUTES))
        raise ValueError(f"unknown button {button!r}; valid: {valid}")
    return normalized


class BackgroundGamepad:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._vg: Any = None
        self._pad: Any = None
        self._buttons = {name: False for name in _BUTTON_ATTRIBUTES}
        self._sticks = {"left": (0.0, 0.0), "right": (0.0, 0.0)}

    def ensure(self) -> None:
        if self._pad is not None:
            return
        try:
            self._vg = importlib.import_module("vgamepad")
            self._pad = self._vg.VX360Gamepad()
        except Exception as exc:
            self._vg = None
            self._pad = None
            raise BackgroundInputError(
                "could not create the ViGEm XInput controller; install this project with [xinput] and verify ViGEmBus"
            ) from exc

    def _set_button(self, name: str, pressed: bool) -> None:
        button = getattr(self._vg.XUSB_BUTTON, _BUTTON_ATTRIBUTES[name])
        if pressed:
            self._pad.press_button(button=button)
        else:
            self._pad.release_button(button=button)
        self._buttons[name] = pressed

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend": "ViGEm/XInput",
                "connected": self._pad is not None,
                "foreground_activation": False,
                "buttons": dict(self._buttons),
                "sticks": dict(self._sticks),
            }

    def press(self, button: str, duration_ms: int = 100) -> dict[str, Any]:
        name = normalize_button(button)
        if not 1 <= duration_ms <= 10_000:
            raise ValueError("duration_ms must be between 1 and 10000")
        with self._lock:
            self.ensure()
            was_pressed = self._buttons[name]
            if not was_pressed:
                self._set_button(name, True)
                self._pad.update()
            try:
                time.sleep(duration_ms / 1000.0)
            finally:
                if not was_pressed:
                    self._set_button(name, False)
                    self._pad.update()
            return {
                "backend": "ViGEm/XInput",
                "button": name,
                "duration_ms": duration_ms,
                "foreground_activation": False,
            }

    def set_buttons(self, buttons: dict[str, bool | None]) -> dict[str, Any]:
        updates: dict[str, bool] = {}
        for button, pressed in buttons.items():
            name = normalize_button(button)
            if pressed is None:
                continue
            if not isinstance(pressed, bool):
                raise ValueError(f"button state for {button!r} must be true, false, or null")
            updates[name] = pressed
        with self._lock:
            self.ensure()
            for name, pressed in updates.items():
                self._set_button(name, pressed)
            self._pad.update()
            return {
                "backend": "ViGEm/XInput",
                "buttons": dict(self._buttons),
                "foreground_activation": False,
            }

    def set_analog(self, x: float, y: float, stick: str = "left") -> dict[str, Any]:
        side = stick.strip().lower()
        if side not in {"left", "right"}:
            raise ValueError("stick must be 'left' or 'right'")
        if not -1.0 <= x <= 1.0 or not -1.0 <= y <= 1.0:
            raise ValueError("x and y must be between -1.0 and 1.0")
        with self._lock:
            self.ensure()
            method = self._pad.left_joystick_float if side == "left" else self._pad.right_joystick_float
            method(x_value_float=float(x), y_value_float=float(y))
            self._sticks[side] = (float(x), float(y))
            self._pad.update()
            return {
                "backend": "ViGEm/XInput",
                "stick": side,
                "x": x,
                "y": y,
                "foreground_activation": False,
            }

    def reset(self) -> dict[str, Any]:
        with self._lock:
            if self._pad is not None:
                self._pad.reset()
                self._pad.update()
            self._buttons = {name: False for name in _BUTTON_ATTRIBUTES}
            self._sticks = {"left": (0.0, 0.0), "right": (0.0, 0.0)}
            return {
                "backend": "ViGEm/XInput",
                "connected": self._pad is not None,
                "foreground_activation": False,
            }

    def close(self) -> None:
        with self._lock:
            if self._pad is not None:
                try:
                    self._pad.reset()
                    self._pad.update()
                except Exception:
                    pass
            self._pad = None
            self._vg = None


gamepad = BackgroundGamepad()
atexit.register(gamepad.close)


def xinput_module_available() -> bool:
    return importlib.util.find_spec("vgamepad") is not None


def choose_backend(backend: str) -> tuple[str, str | None]:
    requested = backend.strip().lower()
    if requested not in {"auto", "keyboard", "xinput"}:
        raise ValueError("backend must be 'auto', 'keyboard', or 'xinput'")
    if requested == "keyboard":
        return "keyboard", None
    try:
        gamepad.ensure()
        return "xinput", None
    except BackgroundInputError as exc:
        if requested == "xinput":
            raise
        return "keyboard", str(exc)


def default_config_candidates() -> list[Path]:
    documents = Path.home() / "Documents" / "PPSSPP" / "PSP" / "SYSTEM" / "ppsspp.ini"
    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
    return [documents, appdata / "PPSSPP" / "PSP" / "SYSTEM" / "ppsspp.ini"]


def _set_ini_values(path: Path, section: str, values: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    section_start = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped.startswith("[") and stripped.endswith("]")):
            continue
        if section_start is not None:
            section_end = index
            break
        if stripped[1:-1].strip().lower() == section.lower():
            section_start = index
    if section_start is None:
        if lines and lines[-1]:
            lines.append("")
        lines.extend([f"[{section}]", *(f"{key} = {value}" for key, value in values.items())])
    else:
        remaining = dict(values)
        for index in range(section_start + 1, section_end):
            key = lines[index].partition("=")[0].strip()
            match = next((name for name in remaining if name.lower() == key.lower()), None)
            if match is not None:
                lines[index] = f"{match} = {remaining.pop(match)}"
        for key, value in remaining.items():
            lines.insert(section_end, f"{key} = {value}")
            section_end += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")


def configure_background_input(config_path: str | None = None) -> dict[str, Any]:
    if config_path:
        path = Path(config_path)
    else:
        path = next((candidate for candidate in default_config_candidates() if candidate.exists()), None)
        if path is None:
            raise FileNotFoundError("PPSSPP config was not found; pass config_path explicitly")
    path = path.resolve()
    backup = path.with_suffix(path.suffix + ".mcp-backup")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    _set_ini_values(
        path,
        "General",
        {"PauseOnLostFocus": "False", "PauseWhenMinimized": "False"},
    )
    _set_ini_values(path, "Control", {"GamepadOnlyFocused": "False"})
    return {
        "path": str(path),
        "backup": str(backup) if backup.exists() else None,
        "values": {
            "General": {"PauseOnLostFocus": "False", "PauseWhenMinimized": "False"},
            "Control": {"GamepadOnlyFocused": "False"},
        },
    }
