from __future__ import annotations

import ctypes
import time
from pathlib import Path
from typing import Any

from . import process_memory


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
gdiplus = ctypes.WinDLL("gdiplus", use_last_error=True)
ole32 = ctypes.OleDLL("ole32")


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class GdiplusStartupInput(ctypes.Structure):
    _fields_ = [
        ("GdiplusVersion", ctypes.c_uint32),
        ("DebugEventCallback", ctypes.c_void_p),
        ("SuppressBackgroundThread", ctypes.c_bool),
        ("SuppressExternalCodecs", ctypes.c_bool),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

user32.EnumWindows.argtypes = [EnumWindowsProc, ctypes.c_void_p]
user32.EnumWindows.restype = ctypes.c_bool
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = ctypes.c_bool
user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
user32.PrintWindow.restype = ctypes.c_bool

gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = ctypes.c_bool
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = ctypes.c_bool
user32.GetWindowDC.argtypes = [ctypes.c_void_p]
user32.GetWindowDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int

gdiplus.GdiplusStartup.argtypes = [
    ctypes.POINTER(ctypes.c_ulonglong),
    ctypes.POINTER(GdiplusStartupInput),
    ctypes.c_void_p,
]
gdiplus.GdiplusStartup.restype = ctypes.c_uint32
gdiplus.GdiplusShutdown.argtypes = [ctypes.c_ulonglong]
gdiplus.GdiplusShutdown.restype = None
gdiplus.GdipCreateBitmapFromHBITMAP.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]
gdiplus.GdipCreateBitmapFromHBITMAP.restype = ctypes.c_uint32
gdiplus.GdipSaveImageToFile.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.POINTER(GUID),
    ctypes.c_void_p,
]
gdiplus.GdipSaveImageToFile.restype = ctypes.c_uint32
gdiplus.GdipDisposeImage.argtypes = [ctypes.c_void_p]
gdiplus.GdipDisposeImage.restype = ctypes.c_uint32
ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(GUID)]
ole32.CLSIDFromString.restype = ctypes.c_long


PW_RENDERFULLCONTENT = 0x00000002
PNG_ENCODER_CLSID = "{557CF406-1A04-11D3-9A73-0000F81EF32E}"


def _last_error(message: str) -> OSError:
    return OSError(ctypes.get_last_error(), message)


def _window_text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(ctypes.c_void_p(hwnd), buffer, len(buffer))
    return buffer.value


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetClassNameW(ctypes.c_void_p(hwnd), buffer, len(buffer))
    return buffer.value


def _rect(hwnd: int) -> RECT:
    rect = RECT()
    if not user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
        raise _last_error(f"GetWindowRect failed for 0x{hwnd:X}")
    return rect


def list_windows(pid: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        window_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(window_pid))
        if pid is not None and int(window_pid.value) != pid:
            return True
        if not user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            return True
        rect = _rect(hwnd)
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return True
        rows.append(
            {
                "hwnd": f"0x{hwnd:X}",
                "pid": int(window_pid.value),
                "title": _window_text(hwnd),
                "class_name": _class_name(hwnd),
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": width,
                "height": height,
            }
        )
        return True

    if not user32.EnumWindows(EnumWindowsProc(callback), None):
        raise _last_error("EnumWindows failed")
    return rows


def find_ppsspp_window(pid: int | None = None) -> dict[str, Any]:
    if pid is None:
        processes = process_memory.find_processes()
        if not processes:
            raise ValueError("no PPSSPP process found")
        pid = int(processes[0]["pid"])
    windows = list_windows(pid)
    candidates = [
        row
        for row in windows
        if "ppsspp" in row["title"].lower() or "ppsspp" in row["class_name"].lower()
    ]
    if not candidates:
        raise ValueError(f"no PPSSPP window found for pid {pid}")
    candidates.sort(key=lambda row: (row["class_name"] != "PPSSPPWnd", -row["width"] * row["height"]))
    return candidates[0]


def _save_hbitmap_png(hbitmap: int, output_path: Path) -> None:
    token = ctypes.c_ulonglong()
    startup = GdiplusStartupInput(1, None, False, False)
    status = gdiplus.GdiplusStartup(ctypes.byref(token), ctypes.byref(startup), None)
    if status:
        raise RuntimeError(f"GdiplusStartup failed: {status}")
    bitmap = ctypes.c_void_p()
    try:
        status = gdiplus.GdipCreateBitmapFromHBITMAP(ctypes.c_void_p(hbitmap), None, ctypes.byref(bitmap))
        if status:
            raise RuntimeError(f"GdipCreateBitmapFromHBITMAP failed: {status}")
        clsid = GUID()
        ole32.CLSIDFromString(PNG_ENCODER_CLSID, ctypes.byref(clsid))
        status = gdiplus.GdipSaveImageToFile(bitmap, str(output_path), ctypes.byref(clsid), None)
        if status:
            raise RuntimeError(f"GdipSaveImageToFile failed: {status}")
    finally:
        if bitmap:
            gdiplus.GdipDisposeImage(bitmap)
        gdiplus.GdiplusShutdown(token)


def capture_window(hwnd: int, output_path: Path) -> dict[str, Any]:
    rect = _rect(hwnd)
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid window size {width}x{height}")

    window_dc = user32.GetWindowDC(ctypes.c_void_p(hwnd))
    if not window_dc:
        raise _last_error("GetWindowDC failed")
    mem_dc = None
    hbitmap = None
    old_object = None
    try:
        mem_dc = gdi32.CreateCompatibleDC(window_dc)
        if not mem_dc:
            raise _last_error("CreateCompatibleDC failed")
        hbitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        if not hbitmap:
            raise _last_error("CreateCompatibleBitmap failed")
        old_object = gdi32.SelectObject(mem_dc, hbitmap)
        if not old_object:
            raise _last_error("SelectObject failed")
        if not user32.PrintWindow(ctypes.c_void_p(hwnd), mem_dc, PW_RENDERFULLCONTENT):
            raise _last_error("PrintWindow failed")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _save_hbitmap_png(hbitmap, output_path)
    finally:
        if old_object and mem_dc:
            gdi32.SelectObject(mem_dc, old_object)
        if hbitmap:
            gdi32.DeleteObject(hbitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(ctypes.c_void_p(hwnd), window_dc)

    return {
        "output_path": str(output_path),
        "hwnd": f"0x{hwnd:X}",
        "left": rect.left,
        "top": rect.top,
        "right": rect.right,
        "bottom": rect.bottom,
        "width": width,
        "height": height,
        "method": "PrintWindow(PW_RENDERFULLCONTENT)",
    }


def default_output_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return root / "logs" / f"ppsspp-window-{stamp}.png"
