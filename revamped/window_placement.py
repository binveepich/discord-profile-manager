"""Bounded, DPM-owned Chromium window placement correction on Windows."""

import ctypes
import sys
import time
from ctypes import wintypes


SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
SWP_NOSENDCHANGING = 0x0400
SWP_NOZORDER = 0x0004
GW_OWNER = 4


def _set_signature(function, argtypes, restype):
    """Set ctypes metadata when given a native function, leaving test doubles intact."""
    try:
        function.argtypes = argtypes
        function.restype = restype
    except (AttributeError, TypeError):
        pass


def _owned_chromium_windows(process_ids):
    """Return visible top-level Chromium HWNDs for the supplied PIDs."""
    if sys.platform != "win32":
        return []
    requested = {int(pid) for pid in process_ids if isinstance(pid, int) and pid > 0}
    if not requested:
        return []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    _set_signature(user32.IsWindowVisible, [wintypes.HWND], wintypes.BOOL)
    _set_signature(user32.GetWindow, [wintypes.HWND, wintypes.UINT], wintypes.HWND)
    _set_signature(
        user32.GetWindowThreadProcessId,
        [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
        wintypes.DWORD,
    )
    _set_signature(
        user32.GetClassNameW,
        [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int],
        ctypes.c_int,
    )
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    handles = []

    @enum_proc_type
    def callback(hwnd, _lparam):
        if _is_owned_chromium_window(user32, hwnd, requested):
            handles.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return handles


def _is_owned_chromium_window(user32, hwnd, requested):
    """Match HWNDs only when visible, top-level, Chromium, and PID-owned."""
    if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if int(pid.value) not in requested:
        return False
    class_name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_name, len(class_name))
    return class_name.value in {"Chrome_WidgetWin_1", "Chrome_WidgetWin_0"}


def move_owned_chromium_window(process_ids, bounds):
    """Move and verify DPM-owned Chromium top-level windows without activating."""
    if sys.platform != "win32" or not isinstance(bounds, dict):
        return False
    try:
        geometry = tuple(int(bounds[key]) for key in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError):
        return False
    if any(value <= 0 for value in geometry[2:]):
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    _set_signature(
        user32.SetWindowPos,
        [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ],
        wintypes.BOOL,
    )
    _set_signature(
        user32.GetWindowRect,
        [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
        wintypes.BOOL,
    )
    flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOSENDCHANGING
    verified = False
    for hwnd in _owned_chromium_windows(process_ids):
        if not user32.SetWindowPos(hwnd, 0, *geometry, flags):
            continue
        actual = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(actual)):
            continue
        observed = (
            actual.left, actual.top,
            actual.right - actual.left, actual.bottom - actual.top,
        )
        verified = verified or observed == geometry
    return verified


def correct_profile_window_placement(
    process_inspector,
    profile_data_dir,
    process,
    bounds,
    *,
    timeout=8.0,
    interval=0.12,
    settle_time=0.8,
):
    """Retry briefly until the launched profile's real window exists.

    The retry is bounded and uses only PIDs that ChromiumProcessInspector has
    matched to the exact ``--user-data-dir`` path. The Popen PID alone is not
    sufficient evidence to identify a window after Chromium startup handoff.
    """
    if sys.platform != "win32":
        return False
    try:
        launched_pid = int(process.pid)
    except (AttributeError, TypeError, ValueError):
        return False
    if launched_pid <= 0:
        return False
    deadline = time.monotonic() + max(0.0, float(timeout))
    settled_until = None
    while True:
        process_ids = set()
        try:
            process_ids.update(process_inspector.process_ids_for_directory(profile_data_dir))
        except Exception:
            # Placement is best-effort; profile launch itself remains valid.
            pass
        verified = move_owned_chromium_window(process_ids, bounds)
        if verified:
            if settled_until is None:
                settled_until = min(deadline, time.monotonic() + max(0.0, float(settle_time)))
            if time.monotonic() >= settled_until:
                return True
        else:
            # A later Chromium restore or a moved/unmapped HWND breaks the
            # stable interval; keep retrying until the bounded deadline.
            settled_until = None
        if time.monotonic() >= deadline:
            return verified
        time.sleep(max(0.02, float(interval)))


__all__ = ["correct_profile_window_placement", "move_owned_chromium_window"]
