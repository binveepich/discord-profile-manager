import unittest
from unittest.mock import patch

from revamped import window_constraints
from revamped.window_constraints import (
    WMSZ_BOTTOM,
    WMSZ_BOTTOMRIGHT,
    WMSZ_LEFT,
    WMSZ_TOP,
    constrain_sizing_rect,
)


def _pointer_value(value):
    if hasattr(value, "value"):
        value = value.value
    if value is None:
        return 0
    return int(value) & ((1 << (window_constraints.ctypes.sizeof(window_constraints.ctypes.c_void_p) * 8)) - 1)


class _FakeFunction:
    def __init__(self, function):
        self.function = function
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.function(*args)


class _FakeUser32:
    def __init__(self):
        self.original_proc = 0x12345678
        self.current_proc = self.original_proc
        self.window_valid = True
        self.set_calls = []
        self.call_calls = []
        self.GetWindowLongPtrW = _FakeFunction(lambda *_args: self.current_proc)
        self.SetWindowLongPtrW = _FakeFunction(self._set_window_long_ptr)
        self.CallWindowProcW = _FakeFunction(self._call_window_proc)
        self.IsZoomed = _FakeFunction(lambda *_args: False)
        self.IsWindow = _FakeFunction(lambda *_args: self.window_valid)

    def _set_window_long_ptr(self, hwnd, index, proc):
        previous = self.current_proc
        self.current_proc = _pointer_value(proc)
        self.set_calls.append((hwnd, index, self.current_proc))
        return previous

    def _call_window_proc(self, proc, *_args):
        self.call_calls.append(_pointer_value(proc))
        return 73


class _FakeIntPtr:
    def __init__(self, value):
        self.value = value

    def ToInt64(self):
        return self.value


class _FakeNativeWindow:
    def __init__(self, hwnd):
        self._handle = _FakeIntPtr(hwnd)
        self._scale = 1.0
        self.IsDisposed = False
        self.IsHandleCreated = True
        self.handle_reads = 0

    @property
    def Handle(self):
        self.handle_reads += 1
        if self.IsDisposed:
            raise AssertionError("disposed Form.Handle must not be accessed")
        return self._handle


class WindowConstraintTests(unittest.TestCase):
    def assert_ratio_and_minimum(self, rect):
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        self.assertGreaterEqual(width, 1312)
        self.assertGreaterEqual(height, 738)
        self.assertLessEqual(abs(width * 9 - height * 16), 16)

    def test_side_resize_preserves_ratio_and_anchor(self):
        rect = constrain_sizing_rect((100, 100, 1300, 800), WMSZ_LEFT)
        self.assertEqual(rect[1], 100)
        self.assertEqual(rect[2], 1300)
        self.assert_ratio_and_minimum(rect)

    def test_vertical_resize_preserves_ratio_and_anchor(self):
        rect = constrain_sizing_rect((100, 100, 1300, 800), WMSZ_TOP)
        self.assertEqual(rect[0], 100)
        self.assertEqual(rect[3], 800)
        self.assert_ratio_and_minimum(rect)

    def test_corner_resize_enforces_minimum_without_polling_or_loop(self):
        rect = constrain_sizing_rect((700, 500, 900, 600), WMSZ_BOTTOMRIGHT)
        self.assertEqual(rect[:2], (700, 500))
        self.assert_ratio_and_minimum(rect)

    def test_minimum_is_exactly_1312_by_738_for_tiny_resize(self):
        self.assertEqual(
            constrain_sizing_rect((300, 300, 350, 350), WMSZ_BOTTOM),
            (300, 300, 1612, 1038),
        )

    def setUp(self):
        self.hwnd = 0x1_2345_6789
        self.window = type("Window", (), {})()
        self.window.native = _FakeNativeWindow(self.hwnd)
        self.user32 = _FakeUser32()
        window_constraints._installed_hooks.clear()
        window_constraints._retained_callbacks.clear()
        self.platform_patch = patch.object(window_constraints.sys, "platform", "win32")
        self.platform_patch.start()
        self.win32_patch = patch.object(
            window_constraints.ctypes,
            "WinDLL",
            return_value=self.user32,
        )
        self.win32_patch.start()
        self.addCleanup(self.win32_patch.stop)
        self.addCleanup(self.platform_patch.stop)
        self.addCleanup(window_constraints._installed_hooks.clear)

    def install_hook(self):
        self.assertTrue(window_constraints.install_aspect_ratio_constraint(self.window))

    def test_install_caches_pointer_width_hwnd_and_callback_state(self):
        self.install_hook()

        state = window_constraints._installed_hooks[id(self.window)]
        self.assertIs(state.window, self.window)
        self.assertEqual(state.hwnd, self.hwnd)
        self.assertEqual(state.original_proc, self.user32.original_proc)
        self.assertEqual(state.callback_pointer, self.user32.current_proc)
        self.assertTrue(callable(state.callback))
        self.assertEqual(self.window.native.handle_reads, 1)

    def test_installed_wndproc_delegates_to_the_original_procedure(self):
        self.install_hook()
        state = window_constraints._installed_hooks[id(self.window)]

        self.assertEqual(state.callback(self.hwnd, 0, 0, 0), 73)
        self.assertEqual(self.user32.call_calls, [self.user32.original_proc])

    def test_remove_uses_cached_state_after_native_form_is_disposed(self):
        self.install_hook()
        self.window.native.IsDisposed = True
        self.window.native.IsHandleCreated = False

        self.assertTrue(window_constraints.remove_aspect_ratio_constraint(self.window))
        self.assertEqual(self.window.native.handle_reads, 1)
        self.assertEqual(self.user32.current_proc, self.user32.original_proc)
        self.assertNotIn(id(self.window), window_constraints._installed_hooks)

    def test_remove_is_safe_when_cached_hwnd_has_been_destroyed(self):
        self.install_hook()
        self.window.native.IsDisposed = True
        self.window.native.IsHandleCreated = False
        self.user32.window_valid = False

        self.assertFalse(window_constraints.remove_aspect_ratio_constraint(self.window))
        self.assertEqual(len(self.user32.set_calls), 1)  # install only
        self.assertNotIn(id(self.window), window_constraints._installed_hooks)

    def test_remove_does_not_overwrite_a_different_or_reused_window_proc(self):
        self.install_hook()
        self.user32.current_proc = 0x76543210

        self.assertFalse(window_constraints.remove_aspect_ratio_constraint(self.window))
        self.assertEqual(self.user32.current_proc, 0x76543210)
        self.assertEqual(len(self.user32.set_calls), 1)  # install only
        self.assertEqual(len(window_constraints._retained_callbacks), 1)

    def test_remove_is_idempotent(self):
        self.install_hook()

        self.assertTrue(window_constraints.remove_aspect_ratio_constraint(self.window))
        self.assertFalse(window_constraints.remove_aspect_ratio_constraint(self.window))
        self.assertEqual(self.user32.current_proc, self.user32.original_proc)

    def test_disposed_shutdown_cleanup_does_not_raise_or_read_handle(self):
        self.install_hook()
        self.window.native.IsDisposed = True
        self.window.native.IsHandleCreated = False

        window_constraints.remove_aspect_ratio_constraint(self.window)
        self.assertEqual(self.window.native.handle_reads, 1)


if __name__ == "__main__":
    unittest.main()
