from __future__ import annotations

import base64
import binascii
import time
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from . import background_input
from . import keyboard_input
from .debugger_client import PPSSPPDebuggerClient, PPSSPPDebuggerError
from . import process_memory
from . import window_capture


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7378
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PSP_BUTTONS = (
    "up",
    "down",
    "left",
    "right",
    "start",
    "select",
    "ltrigger",
    "rtrigger",
    "cross",
    "circle",
    "square",
    "triangle",
)

mcp = MCPServer("ppsspp-mcp")


def _ok(**kw: Any) -> dict[str, Any]:
    return {"ok": True, **kw}


def _err(message: str, **kw: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **kw}


def _debugger(host: str, port: int, timeout: float) -> PPSSPPDebuggerClient:
    return PPSSPPDebuggerClient(host=host, port=port, timeout=timeout)


def _checked_request(client: PPSSPPDebuggerClient, event: str, **params: Any) -> dict[str, Any]:
    response = client.request(event, **params)
    if response.get("event") == "error":
        raise PPSSPPDebuggerError(str(response.get("message", f"{event} failed")))
    return response


def _connect_native(
    backend: str,
    host: str,
    port: int,
    timeout: float,
) -> tuple[PPSSPPDebuggerClient | None, str | None]:
    requested = backend.strip().lower()
    if requested not in {"auto", "native", "keyboard", "xinput"}:
        raise ValueError("backend must be 'auto', 'native', 'keyboard', or 'xinput'")
    if requested not in {"auto", "native"}:
        return None, None

    client = _debugger(host, port, timeout)
    try:
        client.connect()
    except (OSError, PPSSPPDebuggerError) as exc:
        client.close()
        if requested == "native":
            raise
        return None, f"native WebSocket input unavailable: {exc}"
    return client, None


def _fallback_backend(backend: str, native_reason: str | None) -> tuple[str, str | None]:
    selected, fallback_reason = background_input.choose_backend(backend)
    reasons = [reason for reason in (native_reason, fallback_reason) if reason]
    return selected, "; ".join(reasons) if reasons else None


def _normalize_buttons(buttons: dict[str, bool | None]) -> dict[str, bool | None]:
    normalized: dict[str, bool | None] = {}
    for button, pressed in buttons.items():
        name = background_input.normalize_button(button)
        if pressed is not None and not isinstance(pressed, bool):
            raise ValueError(f"button state for {button!r} must be true, false, or null")
        normalized[name] = pressed
    return normalized


def _keyboard_window(pid: int | None) -> tuple[dict[str, Any], int]:
    window = window_capture.find_ppsspp_window(pid)
    return window, int(window["hwnd"], 16)


def _default_screenshot_path() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return _PROJECT_ROOT / "logs" / "screenshots" / f"ppsspp-{stamp}.png"


def _capture_inactive_window(output_path: Path, pid: int | None) -> dict[str, Any]:
    window = window_capture.find_ppsspp_window(pid)
    result = window_capture.capture_window(int(window["hwnd"], 16), output_path)
    return {
        "pid": window["pid"],
        "title": window["title"],
        "class_name": window["class_name"],
        **result,
    }


def _get_pid(pid: int | None) -> int:
    if pid is not None:
        return pid
    processes = process_memory.find_processes()
    if not processes:
        raise ValueError("no PPSSPP process found")
    return int(processes[0]["pid"])


@mcp.tool()
def debugger_status(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Connect to PPSSPP's WebSocket debugger and return game/cpu/thread status."""
    try:
        with _debugger(host, port, timeout) as client:
            game = client.request("game.status")
            cpu = client.request("cpu.status")
            threads = client.request("hle.thread.list")
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port)
    return _ok(game=game, cpu=cpu, threads=threads)


@mcp.tool()
def game_status(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Return PPSSPP game status through the remote debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            return _ok(response=client.request("game.status"))
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port)


@mcp.tool()
def cpu_status(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Return PPSSPP CPU status through the remote debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            return _ok(response=client.request("cpu.status"))
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port)


@mcp.tool()
def thread_list(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """List PSP threads through PPSSPP's HLE debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            return _ok(response=client.request("hle.thread.list"))
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port)


@mcp.tool()
def evaluate(expression: str, thread: int | None = None, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Evaluate a PPSSPP debugger expression. Uses the current thread when thread is omitted."""
    try:
        with _debugger(host, port, timeout) as client:
            if thread is None:
                threads = client.request("hle.thread.list")
                current = [row for row in threads.get("threads", []) if row.get("isCurrent")]
                if not current:
                    return _err("could not determine current thread", threads=threads)
                thread = int(current[0]["id"])
            return _ok(response=client.request("cpu.evaluate", thread=thread, expression=expression))
    except (OSError, PPSSPPDebuggerError, ValueError) as e:
        return _err(str(e), host=host, port=port)


@mcp.tool()
def disassemble(address: int | str, count: int = 16, thread: int | None = None, display_symbols: bool = True, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Disassemble guest code through PPSSPP's native debugger."""
    try:
        addr = process_memory.parse_address(address)
        with _debugger(host, port, timeout) as client:
            if thread is None:
                threads = client.request("hle.thread.list")
                current = [row for row in threads.get("threads", []) if row.get("isCurrent")]
                if not current:
                    return _err("could not determine current thread", threads=threads)
                thread = int(current[0]["id"])
            response = client.request(
                "memory.disasm",
                thread=thread,
                address=addr,
                count=count,
                displaySymbols=display_symbols,
            )
            return _ok(response=response)
    except (OSError, PPSSPPDebuggerError, ValueError) as e:
        return _err(str(e), host=host, port=port)


@mcp.tool()
def pause(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Pause PPSSPP emulation through the debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            status = _checked_request(client, "cpu.status")
            if bool(status.get("stepping", False)):
                return _ok(response=status, already_stepping=True)
            return _ok(response=client.request_event("cpu.stepping"))
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port)


@mcp.tool()
def resume(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Resume PPSSPP emulation through the debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            status = _checked_request(client, "cpu.status")
            if not bool(status.get("stepping", False)):
                return _ok(response=status, already_running=True)
            return _ok(response=client.request_event("cpu.resume"))
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port)


@mcp.tool()
def debugger_request(event: str, params: dict[str, Any] | None = None, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Send a raw ticketed request to the PPSSPP WebSocket debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            return _ok(response=client.request(event, **(params or {})))
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port, event=event)


@mcp.tool()
def input_button_press(
    button: str,
    duration: int = 6,
    backend: str = "auto",
    pid: int | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 5.0,
) -> dict:
    """Press and release a PSP button without activating PPSSPP."""
    native: PPSSPPDebuggerClient | None = None
    try:
        if not 1 <= duration <= 600:
            raise ValueError("duration must be between 1 and 600 frames")
        normalized = background_input.normalize_button(button)
        native, native_reason = _connect_native(backend, host, port, timeout)
        if native is not None:
            try:
                response = _checked_request(
                    native,
                    "input.buttons.press",
                    button=normalized,
                    duration=duration,
                )
            finally:
                native.close()
                native = None
            return _ok(
                selected_backend="native",
                response=response,
                foreground_activation=False,
            )

        selected, fallback_reason = _fallback_backend(backend, native_reason)
        duration_ms = max(1, round(duration * 1000 / 60))
        if selected == "xinput":
            result = background_input.gamepad.press(normalized, duration_ms)
            return _ok(
                selected_backend=selected,
                fallback_reason=fallback_reason,
                duration_frames=duration,
                **result,
            )
        window, hwnd = _keyboard_window(pid)
        result = keyboard_input.keyboard.press(hwnd, normalized, duration_ms)
        return _ok(
            selected_backend=selected,
            fallback_reason=fallback_reason,
            duration_frames=duration,
            input_target=window,
            **result,
        )
    except (
        background_input.BackgroundInputError,
        OSError,
        PPSSPPDebuggerError,
        ValueError,
    ) as e:
        return _err(str(e), host=host, port=port, button=button, backend=backend)
    finally:
        if native is not None:
            native.close()


@mcp.tool()
def input_buttons_send(
    buttons: dict[str, bool | None],
    backend: str = "auto",
    pid: int | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 5.0,
) -> dict:
    """Set PSP button states without activating PPSSPP."""
    native: PPSSPPDebuggerClient | None = None
    try:
        normalized = _normalize_buttons(buttons)
        native, native_reason = _connect_native(backend, host, port, timeout)
        if native is not None:
            try:
                response = _checked_request(native, "input.buttons.send", buttons=normalized)
            finally:
                native.close()
                native = None
            return _ok(
                selected_backend="native",
                response=response,
                foreground_activation=False,
            )

        selected, fallback_reason = _fallback_backend(backend, native_reason)
        if selected == "xinput":
            result = background_input.gamepad.set_buttons(normalized)
            return _ok(
                selected_backend=selected,
                fallback_reason=fallback_reason,
                **result,
            )
        window, hwnd = _keyboard_window(pid)
        result = keyboard_input.keyboard.set_buttons(hwnd, normalized)
        return _ok(
            selected_backend=selected,
            fallback_reason=fallback_reason,
            input_target=window,
            **result,
        )
    except (
        background_input.BackgroundInputError,
        OSError,
        PPSSPPDebuggerError,
        ValueError,
    ) as e:
        return _err(str(e), host=host, port=port, buttons=buttons, backend=backend)
    finally:
        if native is not None:
            native.close()


@mcp.tool()
def input_analog_send(
    x: float,
    y: float,
    stick: str = "left",
    backend: str = "auto",
    pid: int | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 5.0,
) -> dict:
    """Set PSP analog coordinates without activating PPSSPP."""
    native: PPSSPPDebuggerClient | None = None
    try:
        side = stick.strip().lower()
        if side not in {"left", "right"}:
            raise ValueError("stick must be 'left' or 'right'")
        if not -1.0 <= x <= 1.0 or not -1.0 <= y <= 1.0:
            raise ValueError("x and y must be between -1.0 and 1.0")
        native, native_reason = _connect_native(backend, host, port, timeout)
        if native is not None:
            try:
                response = _checked_request(
                    native,
                    "input.analog.send",
                    x=float(x),
                    y=float(y),
                    stick=side,
                )
            finally:
                native.close()
                native = None
            return _ok(
                selected_backend="native",
                response=response,
                foreground_activation=False,
            )

        selected, fallback_reason = _fallback_backend(backend, native_reason)
        if selected == "xinput":
            result = background_input.gamepad.set_analog(x, y, side)
            return _ok(
                selected_backend=selected,
                fallback_reason=fallback_reason,
                **result,
            )
        window, hwnd = _keyboard_window(pid)
        result = keyboard_input.keyboard.set_analog(hwnd, x, y, side)
        return _ok(
            selected_backend=selected,
            fallback_reason=fallback_reason,
            input_target=window,
            **result,
        )
    except (
        background_input.BackgroundInputError,
        OSError,
        PPSSPPDebuggerError,
        ValueError,
    ) as e:
        return _err(str(e), host=host, port=port, x=x, y=y, stick=stick, backend=backend)
    finally:
        if native is not None:
            native.close()


@mcp.tool()
def input_reset(
    backend: str = "auto",
    pid: int | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 5.0,
) -> dict:
    """Release native, keyboard, and virtual-controller input without focus."""
    native: PPSSPPDebuggerClient | None = None
    try:
        requested = backend.strip().lower()
        native, native_reason = _connect_native(requested, host, port, timeout)
        if native is not None:
            try:
                button_response = _checked_request(
                    native,
                    "input.buttons.send",
                    buttons={button: False for button in _PSP_BUTTONS},
                )
                analog_responses = [
                    _checked_request(native, "input.analog.send", x=0.0, y=0.0, stick=stick)
                    for stick in ("left", "right")
                ]
            finally:
                native.close()
                native = None
            if requested == "native":
                return _ok(
                    selected_backend="native",
                    buttons=button_response,
                    analog=analog_responses,
                    foreground_activation=False,
                )
        else:
            button_response = None
            analog_responses = None

        if requested == "xinput":
            return _ok(selected_backend="xinput", **background_input.gamepad.reset())

        keyboard_result = None
        input_window = None
        if requested in {"auto", "keyboard"}:
            try:
                input_window, hwnd = _keyboard_window(pid)
                keyboard_result = keyboard_input.keyboard.reset(hwnd)
            except (OSError, ValueError):
                if requested == "keyboard":
                    raise

        xinput_result = (
            background_input.gamepad.reset()
            if requested == "auto" and background_input.gamepad.status()["connected"]
            else None
        )
        return _ok(
            native=button_response,
            native_analog=analog_responses,
            native_fallback_reason=native_reason,
            keyboard=keyboard_result,
            xinput=xinput_result,
            input_target=input_window,
            foreground_activation=False,
        )
    except (
        background_input.BackgroundInputError,
        OSError,
        PPSSPPDebuggerError,
        ValueError,
    ) as e:
        return _err(str(e), host=host, port=port, backend=backend)
    finally:
        if native is not None:
            native.close()


@mcp.tool()
def configure_background_input(config_path: str | None = None) -> dict:
    """Keep PPSSPP running and accepting gamepad input while inactive."""
    try:
        return _ok(**background_input.configure_background_input(config_path))
    except (OSError, ValueError) as e:
        return _err(str(e), config_path=config_path)


@mcp.tool()
def background_input_status(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 0.5,
) -> dict:
    """Return native, XInput, and patched-keyboard backend availability."""
    native_available = False
    native_error = None
    client = _debugger(host, port, timeout)
    try:
        client.connect()
        native_available = True
    except (OSError, PPSSPPDebuggerError) as e:
        native_error = str(e)
    finally:
        client.close()
    return _ok(
        default_backend="auto",
        auto_order=["native", "xinput", "keyboard"],
        native={
            "available": native_available,
            "backend": "PPSSPP WebSocket debugger",
            "error": native_error,
        },
        xinput_module_available=background_input.xinput_module_available(),
        xinput=background_input.gamepad.status(),
        keyboard={
            "backend": "PPSSPP.MCP.BackgroundKey",
            "requires_patched_build": True,
        },
        foreground_activation=False,
    )


@mcp.tool()
def list_ppsspp_processes() -> dict:
    """List running PPSSPP processes."""
    return _ok(processes=process_memory.find_processes())


@mcp.tool()
def list_ppsspp_windows(pid: int | None = None) -> dict:
    """List visible PPSSPP windows. If pid is omitted, uses the first PPSSPP process."""
    try:
        target_pid = _get_pid(pid)
        return _ok(pid=target_pid, windows=window_capture.list_windows(target_pid))
    except (OSError, ValueError) as e:
        return _err(str(e), pid=pid)


@mcp.tool()
def take_screenshot(
    output_path: str | None = None,
    pid: int | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 15.0,
) -> dict:
    """Capture the rendered PSP frame natively, with inactive PrintWindow fallback."""
    try:
        out = _default_screenshot_path() if output_path is None else Path(output_path)
        if not out.is_absolute():
            out = Path.cwd() / out
        out = out.resolve()
        if out.suffix.lower() != ".png":
            raise ValueError("PPSSPP screenshots require a .png output path")

        native_error = None
        try:
            with _debugger(host, port, timeout) as client:
                status = _checked_request(client, "cpu.status")
                resume_after_capture = not bool(status.get("stepping", False))
                if resume_after_capture:
                    client.request_event("cpu.stepping")
                try:
                    response = _checked_request(client, "gpu.buffer.screenshot", type="uri")
                finally:
                    if resume_after_capture:
                        client.request_event("cpu.resume")
            uri = response.get("uri")
            if not isinstance(uri, str):
                raise PPSSPPDebuggerError("gpu.buffer.screenshot returned no PNG data URI")
            header, separator, payload = uri.partition(",")
            if separator != "," or header != "data:image/png;base64":
                raise PPSSPPDebuggerError("gpu.buffer.screenshot returned an unsupported data URI")
            data = base64.b64decode(payload, validate=True)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            return _ok(
                output_path=str(out),
                size=len(data),
                width=response.get("width"),
                height=response.get("height"),
                is_framebuffer=bool(response.get("isFramebuffer", False)),
                method="gpu.buffer.screenshot",
                foreground_activation=False,
            )
        except (binascii.Error, OSError, PPSSPPDebuggerError, ValueError) as e:
            native_error = str(e)

        result = _capture_inactive_window(out, pid)
        return _ok(
            **result,
            native_error=native_error,
            fallback="inactive-window",
            foreground_activation=False,
        )
    except (OSError, ValueError, RuntimeError) as e:
        return _err(
            str(e),
            pid=pid,
            output_path=output_path,
            host=host,
            port=port,
        )


@mcp.tool()
def capture_ppsspp_window(output_path: str | None = None, pid: int | None = None) -> dict:
    """Capture an inactive PPSSPP window without restoring or activating it."""
    try:
        out = window_capture.default_output_path() if output_path is None else Path(output_path)
        if not out.is_absolute():
            out = Path.cwd() / out
        result = _capture_inactive_window(out.resolve(), pid)
        return _ok(**result, foreground_activation=False)
    except (OSError, ValueError, RuntimeError) as e:
        return _err(str(e), pid=pid, output_path=output_path)


@mcp.tool()
def launch_ppsspp(exe_path: str, game_path: str | None = None, extra_args: list[str] | None = None) -> dict:
    """Launch PPSSPP, optionally with a game path."""
    return process_memory.launch(exe_path, game_path, extra_args)


@mcp.tool()
def list_process_regions(pid: int | None = None) -> dict:
    """List committed readable virtual-memory regions for a PPSSPP process."""
    try:
        target_pid = _get_pid(pid)
        with process_memory.WindowsProcessMemory(target_pid) as mem:
            return _ok(pid=target_pid, regions=mem.regions())
    except (OSError, ValueError) as e:
        return _err(str(e), pid=pid)


@mcp.tool()
def read_process_memory(address: int | str, length: int, pid: int | None = None, as_format: str = "hex") -> dict:
    """Read host-process memory from PPSSPP. Address is a host virtual address."""
    try:
        target_pid = _get_pid(pid)
        addr = process_memory.parse_address(address)
        with process_memory.WindowsProcessMemory(target_pid) as mem:
            data = mem.read(addr, length)
    except (OSError, ValueError) as e:
        return _err(str(e), pid=pid, address=address)

    result: dict[str, Any] = {"pid": target_pid, "host_address": f"0x{addr:X}", "length": len(data)}
    if as_format == "hex":
        result["hex"] = data.hex()
    elif as_format == "base64":
        result["base64"] = base64.b64encode(data).decode("ascii")
    elif as_format == "ascii":
        result["ascii"] = data.decode("ascii", errors="replace")
    else:
        return _err(f"unknown as_format: {as_format}")
    return _ok(**result)


@mcp.tool()
def find_process_pattern(
    pattern: str,
    pid: int | None = None,
    max_results: int = 64,
    context: int = 16,
    start_address: int | str | None = None,
    end_address: int | str | None = None,
) -> dict:
    """Search PPSSPP host-process memory for a hex pattern. Use ?? for wildcard bytes."""
    try:
        target_pid = _get_pid(pid)
        parsed = process_memory.parse_pattern(pattern)
        start = process_memory.parse_address(start_address) if start_address is not None else None
        end = process_memory.parse_address(end_address) if end_address is not None else None
        with process_memory.WindowsProcessMemory(target_pid) as mem:
            hits = mem.find_pattern(parsed, max_results=max_results, context=context, start_address=start, end_address=end)
    except (OSError, ValueError) as e:
        return _err(str(e), pid=pid, pattern=pattern)
    return _ok(pid=target_pid, pattern=pattern, count=len(hits), hits=hits)


@mcp.tool()
def pattern_from_text(text: str, encoding: str = "utf-8") -> dict:
    """Encode text as a hex pattern using a Python codec such as utf-8 or shift_jis."""
    try:
        raw = text.encode(encoding)
    except LookupError as e:
        return _err(f"unknown encoding: {encoding}", error_detail=str(e))
    except UnicodeEncodeError as e:
        return _err(f"text cannot be encoded as {encoding}", error_detail=str(e))
    return _ok(text=text, encoding=encoding, pattern=raw.hex())
