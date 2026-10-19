"""Native Windows sizing constraints for the product window.

The pure rectangle helper is kept separate from the Win32 hook so the sizing
policy can be tested without creating a desktop window.  The hook changes the
rectangle supplied by ``WM_SIZING`` in-place; it never calls SetWindowPos and
therefore does not create a resize feedback loop.
"""

import ctypes
import sys
from dataclasses import dataclass
from ctypes import wintypes


ASPECT_RATIO = 16 / 9
MIN_WINDOW_SIZE = (1312, 738)
WM_SIZING = 0x0214
GWLP_WNDPROC = -4
WMSZ_LEFT = 1
WMSZ_RIGHT = 2
WMSZ_TOP = 3
WMSZ_TOPLEFT = 4
WMSZ_TOPRIGHT = 5
WMSZ_BOTTOM = 6
WMSZ_BOTTOMLEFT = 7
WMSZ_BOTTOMRIGHT = 8


def constrain_sizing_rect(rect, edge, *, min_size=MIN_WINDOW_SIZE, ratio=ASPECT_RATIO):
    """Return a minimum-sized, fixed-ratio rectangle for one resize edge.

    ``rect`` is ``(left, top, right, bottom)`` in screen coordinates.  The
    opposite edge/corner remains anchored, matching normal Windows resizing.
    """
    left, top, right, bottom = (int(value) for value in rect)
    min_width, min_height = (max(1, int(value)) for value in min_size)
    ratio = float(ratio)
    if ratio <= 0:
        raise ValueError("ratio must be positive")

    requested_width = max(1, right - left)
    requested_height = max(1, bottom - top)
    horizontal_edges = {WMSZ_LEFT, WMSZ_RIGHT}
    vertical_edges = {WMSZ_TOP, WMSZ_BOTTOM}

    if edge in vertical_edges:
        height = max(min_height, requested_height)
        width = max(min_width, round(height * ratio))
    else:
        width = max(min_width, requested_width)
        height = max(min_height, round(width / ratio))

    if edge in {WMSZ_LEFT, WMSZ_TOPLEFT, WMSZ_BOTTOMLEFT}:
        left = right - width
    else:
        right = left + width
    if edge in {WMSZ_TOP, WMSZ_TOPLEFT, WMSZ_TOPRIGHT}:
        top = bottom - height
    else:
        bottom = top + height

    # A malformed/custom edge should still return a valid ratio-constrained
    # rectangle instead of allowing a native callback exception to escape.
    if edge not in horizontal_edges | vertical_edges | {
        WMSZ_TOPLEFT, WMSZ_TOPRIGHT, WMSZ_BOTTOMLEFT, WMSZ_BOTTOMRIGHT,
    }:
        right = left + width
        bottom = top + height
    return left, top, right, bottom


@dataclass
class _InstalledHook:
    window: object
    hwnd: int
    user32: object
    original_proc: int
    callback: object
    callback_pointer: int


# Key by the pywebview Window identity, not by HWND. HWND values can be reused
# after Form disposal, while the owning Window object remains unambiguous.
_installed_hooks = {}
_retained_callbacks = []


def _pointer_value(value):
    """Normalize LONG_PTR values returned as signed or unsigned Python ints."""
    if value is None:
        return 0
    if hasattr(value, "value"):
        value = value.value
    if value is None:
        return 0
    mask = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1
    return int(value) & mask


def _native_hwnd(native):
    """Read an IntPtr without truncating 64-bit HWND values."""
    handle = native.Handle
    to_int64 = getattr(handle, "ToInt64", None)
    hwnd = int(to_int64()) if callable(to_int64) else int(handle)
    return hwnd


def install_aspect_ratio_constraint(window, *, min_size=MIN_WINDOW_SIZE, ratio=ASPECT_RATIO):
    """Install a one-time Win32 ``WM_SIZING`` constraint on a pywebview window.

    Returns ``True`` only when a native Win32 window procedure was installed.
    Non-Windows/headless callers safely receive ``False``.
    """
    if sys.platform != "win32" or window is None:
        return False
    key = id(window)
    installed = _installed_hooks.get(key)
    if installed is not None and installed.window is window:
        return True
    native = getattr(window, "native", None)
    if native is None:
        return False
    try:
        if bool(getattr(native, "IsDisposed", False)) or not bool(
            getattr(native, "IsHandleCreated", True)
        ):
            return False
        hwnd = _native_hwnd(native)
        scale = float(getattr(native, "_scale", 1.0) or 1.0)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    if hwnd == 0:
        return False

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    wnd_proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.IsZoomed.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL

    original = _pointer_value(user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC))
    if original == 0:
        return False
    original_pointer = ctypes.c_void_p(original)
    physical_min_size = tuple(max(1, round(int(value) * scale)) for value in min_size)

    @wnd_proc_type
    def wnd_proc(message_hwnd, message, wparam, lparam):
        if message == WM_SIZING and not user32.IsZoomed(message_hwnd) and lparam:
            try:
                native_rect = ctypes.cast(lparam, ctypes.POINTER(RECT)).contents
                constrained = constrain_sizing_rect(
                    (native_rect.left, native_rect.top, native_rect.right, native_rect.bottom),
                    int(wparam),
                    min_size=physical_min_size,
                    ratio=ratio,
                )
                native_rect.left, native_rect.top, native_rect.right, native_rect.bottom = constrained
            except (ValueError, TypeError):
                pass
        return user32.CallWindowProcW(original_pointer, message_hwnd, message, wparam, lparam)

    callback_pointer = ctypes.cast(wnd_proc, ctypes.c_void_p).value
    result = user32.SetWindowLongPtrW(
        hwnd,
        GWLP_WNDPROC,
        ctypes.c_void_p(callback_pointer),
    )
    if _pointer_value(result) == 0:
        return False
    _installed_hooks[key] = _InstalledHook(
        window=window,
        hwnd=hwnd,
        user32=user32,
        original_proc=original,
        callback=wnd_proc,
        callback_pointer=callback_pointer,
    )
    return True


def remove_aspect_ratio_constraint(window):
    """Restore a previous hook without reading the possibly disposed Form."""
    if sys.platform != "win32" or window is None:
        return False
    key = id(window)
    hook = _installed_hooks.get(key)
    if hook is None or hook.window is not window:
        return False

    # Consume the state first so repeated shutdown cleanup is always harmless.
    _installed_hooks.pop(key, None)
    user32 = hook.user32
    hwnd = hook.hwnd
    if not user32.IsWindow(hwnd):
        return False

    # Do not overwrite another subclass (or a different window that reused
    # this HWND). The callback is retained in case another WndProc chained it.
    current_proc = _pointer_value(user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC))
    if current_proc != hook.callback_pointer:
        _retained_callbacks.append(hook.callback)
        return False

    previous_proc = user32.SetWindowLongPtrW(
        hwnd,
        GWLP_WNDPROC,
        ctypes.c_void_p(hook.original_proc),
    )
    if _pointer_value(previous_proc) != hook.callback_pointer:
        _retained_callbacks.append(hook.callback)
        return False
    return True


__all__ = [
    "ASPECT_RATIO",
    "MIN_WINDOW_SIZE",
    "constrain_sizing_rect",
    "install_aspect_ratio_constraint",
    "remove_aspect_ratio_constraint",
]
