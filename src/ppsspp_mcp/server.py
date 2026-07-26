from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .debugger_client import PPSSPPDebuggerClient, PPSSPPDebuggerError
from . import process_memory
from . import window_capture


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7378

mcp = FastMCP("ppsspp-mcp")


def _ok(**kw: Any) -> dict[str, Any]:
    return {"ok": True, **kw}


def _err(message: str, **kw: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **kw}


def _debugger(host: str, port: int, timeout: float) -> PPSSPPDebuggerClient:
    return PPSSPPDebuggerClient(host=host, port=port, timeout=timeout)


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
            client.request("game.pause")
            return _ok()
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port)


@mcp.tool()
def resume(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Resume PPSSPP emulation through the debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            client.request("game.resume")
            return _ok()
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
def input_button_press(button: str, duration: int = 6, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Press and release a PSP button through PPSSPP's WebSocket debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            return _ok(response=client.request("input.buttons.press", button=button, duration=duration))
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port, button=button)


@mcp.tool()
def input_buttons_send(buttons: dict[str, bool | None], host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Set PSP button states through PPSSPP's WebSocket debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            return _ok(response=client.request("input.buttons.send", buttons=buttons))
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port, buttons=buttons)


@mcp.tool()
def input_analog_send(x: float, y: float, stick: str = "left", host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0) -> dict:
    """Set PSP analog stick coordinates through PPSSPP's WebSocket debugger."""
    try:
        with _debugger(host, port, timeout) as client:
            return _ok(response=client.request("input.analog.send", x=x, y=y, stick=stick))
    except (OSError, PPSSPPDebuggerError) as e:
        return _err(str(e), host=host, port=port, x=x, y=y, stick=stick)


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
def capture_ppsspp_window(output_path: str | None = None, pid: int | None = None, restore: bool = True) -> dict:
    """Capture the PPSSPP window with PrintWindow, even when it is inactive or covered."""
    try:
        window = window_capture.find_ppsspp_window(pid)
        out = window_capture.default_output_path() if output_path is None else Path(output_path)
        if not out.is_absolute():
            out = Path.cwd() / out
        result = window_capture.capture_window(int(window["hwnd"], 16), out, restore=restore)
        return _ok(pid=window["pid"], title=window["title"], class_name=window["class_name"], **result)
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
