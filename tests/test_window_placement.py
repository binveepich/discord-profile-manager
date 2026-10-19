import ctypes
from ctypes import wintypes
from pathlib import Path
import unittest
from unittest.mock import patch

from revamped import window_placement
from revamped.processes import ChromiumProcessInspector


class _Process:
    pid = 4242


class _Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class _WindowApi:
    def __init__(self, *, accept_move=True):
        self.accept_move = accept_move
        self.positions = []
        self.windows = {
            100: {"pid": 1000, "visible": True, "owner": 0, "class": "DPMWindow", "rect": (0, 0, 640, 480)},
            101: {"pid": 4242, "visible": True, "owner": 0, "class": "Chrome_WidgetWin_1", "rect": (0, 0, 640, 480)},
            102: {"pid": 7000, "visible": True, "owner": 0, "class": "Chrome_WidgetWin_1", "rect": (0, 0, 640, 480)},
            103: {"pid": 4242, "visible": False, "owner": 0, "class": "Chrome_WidgetWin_1", "rect": (0, 0, 640, 480)},
            104: {"pid": 4242, "visible": True, "owner": 100, "class": "Chrome_WidgetWin_1", "rect": (0, 0, 640, 480)},
            105: {"pid": 4242, "visible": True, "owner": 0, "class": "OtherWindow", "rect": (0, 0, 640, 480)},
        }

    @staticmethod
    def _key(hwnd):
        return hwnd if isinstance(hwnd, int) else hwnd.value

    def IsWindowVisible(self, hwnd):
        return self.windows[self._key(hwnd)]["visible"]

    def GetWindow(self, hwnd, _command):
        return self.windows[self._key(hwnd)]["owner"]

    def GetWindowThreadProcessId(self, hwnd, output):
        ctypes.cast(output, ctypes.POINTER(wintypes.DWORD))[0] = self.windows[self._key(hwnd)]["pid"]
        return 1

    def GetClassNameW(self, hwnd, output, _size):
        output.value = self.windows[self._key(hwnd)]["class"]
        return len(output.value)

    def EnumWindows(self, callback, parameter):
        for hwnd in self.windows:
            callback(hwnd, parameter)
        return 1

    def SetWindowPos(self, hwnd, _after, x, y, width, height, _flags):
        key = self._key(hwnd)
        self.positions.append(key)
        if self.accept_move:
            self.windows[key]["rect"] = (x, y, x + width, y + height)
        return 1

    def GetWindowRect(self, hwnd, output):
        left, top, right, bottom = self.windows[self._key(hwnd)]["rect"]
        rect = ctypes.cast(output, ctypes.POINTER(wintypes.RECT)).contents
        rect.left, rect.top, rect.right, rect.bottom = left, top, right, bottom
        return 1


class WindowPlacementTests(unittest.TestCase):
    def test_correction_retries_if_chromium_restores_bounds_during_startup(self):
        clock = _Clock()
        moved = []

        def move(process_ids, bounds):
            moved.append((process_ids, bounds))
            return len(moved) != 2

        with patch.object(window_placement.sys, "platform", "win32"), \
             patch.object(window_placement.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(window_placement.time, "sleep", side_effect=clock.sleep), \
             patch.object(window_placement, "move_owned_chromium_window", side_effect=move):
            result = window_placement.correct_profile_window_placement(
                process_inspector=type(
                    "Inspector", (),
                    {"process_ids_for_directory": lambda self, _path: {5000}},
                )(),
                profile_data_dir="profile_0002",
                process=_Process(),
                bounds={"x": 100, "y": 50, "width": 600, "height": 400},
                timeout=2.0,
                interval=0.1,
                settle_time=0.3,
            )

        self.assertTrue(result)
        self.assertGreaterEqual(len(moved), 6)
        self.assertEqual(moved[0][0], {5000})

    def test_correction_stops_at_bounded_deadline_when_no_window_exists(self):
        clock = _Clock()
        with patch.object(window_placement.sys, "platform", "win32"), \
             patch.object(window_placement.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(window_placement.time, "sleep", side_effect=clock.sleep), \
             patch.object(window_placement, "move_owned_chromium_window", return_value=False) as move:
            result = window_placement.correct_profile_window_placement(
                process_inspector=type(
                    "Inspector", (),
                    {"process_ids_for_directory": lambda self, _path: set()},
                )(),
                profile_data_dir="profile_0003",
                process=_Process(),
                bounds={"x": 100, "y": 50, "width": 600, "height": 400},
                timeout=2.0,
                interval=1.0,
            )

        self.assertFalse(result)
        self.assertEqual(move.call_count, 3)

    def test_first_three_profiles_keep_exact_user_data_directory_to_process_mapping(self):
        class FakePsutil:
            class Error(Exception):
                pass

            class NoSuchProcess(Error):
                pass

            class AccessDenied(Error):
                pass

        class FakeProcess:
            def __init__(self, pid, path):
                self.pid = pid
                self.info = {"name": "chrome.exe"}
                self.path = Path(path)

            def cmdline(self):
                return ["chrome.exe", f"--user-data-dir={self.path}"]

        root = Path("C:/DPM-test/profiles")
        process_map = {
            root / "profile_0001": 101,
            root / "profile_0002": 202,
            root / "profile_0003": 303,
        }
        processes = [FakeProcess(pid, path) for path, pid in process_map.items()]
        processes.append(FakeProcess(999, root / "unrelated"))
        inspector = ChromiumProcessInspector(
            process_iter=lambda *_args: processes,
            psutil_module=FakePsutil,
        )

        for directory, expected_pid in process_map.items():
            with self.subTest(profile=directory.name):
                self.assertEqual(
                    inspector.process_ids_for_directory(directory), {expected_pid}
                )

        correction_pids = []
        with patch.object(window_placement.sys, "platform", "win32"), \
             patch.object(window_placement.time, "monotonic", return_value=0), \
             patch.object(
                 window_placement,
                 "move_owned_chromium_window",
                 side_effect=lambda pids, _bounds: correction_pids.append(pids) or True,
             ):
            for directory in process_map:
                self.assertTrue(window_placement.correct_profile_window_placement(
                    process_inspector=inspector,
                    profile_data_dir=directory,
                    process=_Process(),
                    bounds={"x": 100, "y": 50, "width": 600, "height": 400},
                    timeout=0,
                    settle_time=0,
                ))

        self.assertEqual(correction_pids, [{101}, {202}, {303}])

    def test_hwnd_matching_excludes_manager_unrelated_and_non_top_level_windows(self):
        user32 = _WindowApi()
        with patch.object(window_placement.sys, "platform", "win32"), \
             patch.object(window_placement.ctypes, "WinDLL", return_value=user32):
            moved = window_placement.move_owned_chromium_window(
                {4242}, {"x": 100, "y": 50, "width": 600, "height": 400}
            )

        self.assertTrue(moved)
        self.assertEqual(user32.positions, [101])
        self.assertEqual(user32.windows[101]["rect"], (100, 50, 700, 450))

    def test_hwnd_move_success_is_rejected_when_readback_rect_does_not_match(self):
        user32 = _WindowApi(accept_move=False)
        with patch.object(window_placement.sys, "platform", "win32"), \
             patch.object(window_placement.ctypes, "WinDLL", return_value=user32):
            moved = window_placement.move_owned_chromium_window(
                {4242}, {"x": 100, "y": 50, "width": 600, "height": 400}
            )

        self.assertFalse(moved)
        self.assertEqual(user32.positions, [101])


if __name__ == "__main__":
    unittest.main()
