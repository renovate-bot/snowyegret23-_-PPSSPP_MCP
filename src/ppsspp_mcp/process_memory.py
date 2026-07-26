from __future__ import annotations

import ctypes
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil


PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01


def _hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is None:
        return None
    startupinfo = startupinfo_type()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return startupinfo


def _matches_ppsspp(value: str | None) -> bool:
    if not value:
        return False
    return "ppsspp" in value.lower()


def find_processes() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
        try:
            info = proc.info
            if _matches_ppsspp(info.get("name")) or _matches_ppsspp(info.get("exe")):
                out.append(
                    {
                        "pid": info["pid"],
                        "name": info.get("name"),
                        "exe": info.get("exe"),
                        "cmdline": info.get("cmdline"),
                        "created": info.get("create_time"),
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def launch(exe_path: str, game_path: str | None = None, extra_args: list[str] | None = None) -> dict[str, Any]:
    exe = Path(exe_path)
    if not exe.exists():
        return {"ok": False, "error": f"PPSSPP executable not found: {exe}"}
    args = [str(exe)]
    if game_path:
        args.append(str(Path(game_path)))
    if extra_args:
        args.extend(extra_args)

    root = Path(__file__).resolve().parents[2]
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"ppsspp-{time.strftime('%Y%m%d-%H%M%S')}.log"
    creationflags = 0
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log = log_path.open("ab")
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(exe.parent),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=True,
            startupinfo=_hidden_startupinfo(),
        )
    finally:
        log.close()
    return {"ok": True, "pid": proc.pid, "args": args, "log_path": str(log_path)}


def parse_address(value: int | str) -> int:
    if isinstance(value, int):
        return value
    text = value.strip()
    return int(text, 16 if text.lower().startswith("0x") else 0)


def parse_pattern(pattern: str) -> list[int | None]:
    compact = re.sub(r"\s+", "", pattern)
    if len(compact) % 2:
        raise ValueError("pattern must contain full bytes")
    out: list[int | None] = []
    for offset in range(0, len(compact), 2):
        part = compact[offset : offset + 2]
        if part == "??":
            out.append(None)
            continue
        out.append(int(part, 16))
    if not out:
        raise ValueError("pattern must not be empty")
    return out


def pattern_to_bytes(pattern: list[int | None]) -> bytes | None:
    if any(byte is None for byte in pattern):
        return None
    return bytes(byte for byte in pattern if byte is not None)


def find_pattern_offsets(data: bytes, pattern: list[int | None], base: int, limit: int) -> list[int]:
    if not pattern or len(pattern) > len(data):
        return []
    raw = pattern_to_bytes(pattern)
    matches: list[int] = []
    if raw is not None:
        start = 0
        while True:
            index = data.find(raw, start)
            if index < 0:
                return matches
            matches.append(base + index)
            if len(matches) >= limit:
                return matches
            start = index + 1
    last_start = len(data) - len(pattern)
    for offset in range(last_start + 1):
        for index, expected in enumerate(pattern):
            if expected is not None and data[offset + index] != expected:
                break
        else:
            matches.append(base + offset)
            if len(matches) >= limit:
                return matches
    return matches


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_ulong),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
    ]


class WindowsProcessMemory:
    def __init__(self, pid: int):
        self.pid = pid
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle = self._kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not self._handle:
            raise OSError(ctypes.get_last_error(), f"OpenProcess failed for pid {pid}")

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._kernel32.CloseHandle(handle)
            self._handle = None

    def __enter__(self) -> "WindowsProcessMemory":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()

    def regions(self) -> list[dict[str, int]]:
        out: list[dict[str, int]] = []
        mbi = MEMORY_BASIC_INFORMATION()
        address = 0
        while address < 0x7FFF00000000:
            size = self._kernel32.VirtualQueryEx(
                self._handle,
                ctypes.c_void_p(address),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi),
            )
            if not size:
                break
            base = int(mbi.BaseAddress or 0)
            region_size = int(mbi.RegionSize)
            protect = int(mbi.Protect)
            if mbi.State == MEM_COMMIT and not (protect & PAGE_GUARD) and (protect & 0xFF) != PAGE_NOACCESS:
                out.append({"base": base, "size": region_size, "protect": protect, "type": int(mbi.Type)})
            next_address = base + region_size
            if next_address <= address:
                break
            address = next_address
        return out

    def read(self, address: int, length: int) -> bytes:
        if length < 0:
            raise ValueError("length must be non-negative")
        buffer = ctypes.create_string_buffer(length)
        read = ctypes.c_size_t()
        ok = self._kernel32.ReadProcessMemory(
            self._handle,
            ctypes.c_void_p(address),
            buffer,
            length,
            ctypes.byref(read),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), f"ReadProcessMemory failed at 0x{address:X}")
        return buffer.raw[: read.value]

    def find_pattern(
        self,
        pattern: list[int | None],
        max_results: int = 64,
        context: int = 16,
        start_address: int | None = None,
        end_address: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        overlap = max(0, min(4096, len(pattern) + context))
        for region in self.regions():
            base = region["base"]
            size = region["size"]
            region_end = base + size
            if start_address is not None and region_end <= start_address:
                continue
            if end_address is not None and base >= end_address:
                continue
            read_start = max(base, start_address or base)
            read_end = min(region_end, end_address or region_end)
            offset = read_start - base
            tail = b""
            while base + offset < read_end and len(hits) < max_results:
                length = min(chunk_size, read_end - (base + offset))
                try:
                    data = self.read(base + offset, length)
                except OSError:
                    offset += length
                    tail = b""
                    continue
                combined = tail + data
                combined_base = base + offset - len(tail)
                for hit in find_pattern_offsets(combined, pattern, combined_base, max_results - len(hits)):
                    ctx_start = max(0, hit - combined_base - context)
                    ctx_end = min(len(combined), hit - combined_base + len(pattern) + context)
                    hits.append(
                        {
                            "host_address": f"0x{hit:X}",
                            "region_base": f"0x{base:X}",
                            "region_offset": f"0x{hit - base:X}",
                            "context_hex": combined[ctx_start:ctx_end].hex(),
                        }
                    )
                    if len(hits) >= max_results:
                        break
                tail = combined[-overlap:] if overlap else b""
                offset += length
        return hits
