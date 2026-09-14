"""M1 regressions using disposable workspace data and mocked browser processes."""

import ctypes
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "legacy" / "profile_manager.py"
TEST_ROOT = PROJECT_ROOT / "tmp"


def load_manager(script_path=SOURCE):
    """Execute the real module, suppressing only its import-time log setup."""
    module = types.ModuleType("profile_manager_m1_test")
    module.__file__ = str(script_path)
    with patch.object(Path, "mkdir"), patch.object(logging, "FileHandler"), patch.object(logging, "basicConfig"):
        exec(compile(SOURCE.read_text(encoding="utf-8"), str(SOURCE), "exec"), module.__dict__)
    module.logger = Mock()
    return module


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = load_manager()

    def setUp(self):
        TEST_ROOT.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="m1_", dir=TEST_ROOT)
        self.work = Path(self.temp.name).resolve()
        self.addCleanup(self.cleanup_workspace)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.data = self.work / "legacy" / "data"
        self.profiles = self.work / "profiles"
        self.config = self.work / "config"
        self.runtime = self.work / "browser" / "chrome.exe"
        self.extensions = self.work / "extensions"
        for name, value in {
            "DATA_DIR": self.data,
            "PROFILES_DIR": self.profiles,
            "CONFIG_DIR": self.config,
            "PROFILES_JSON": self.config / "profiles.json",
            "LOCAL_STATE": self.data / "Local State",
            "BROWSER_EXE": self.runtime,
            "EXT_DIR": self.extensions / "discord-autofill-extension",
            "TOKEN_EXT_DIR": self.extensions / "discord-token-extractor-extension",
        }.items():
            self.stack.enter_context(patch.object(self.manager, name, value))
        self.popen = self.stack.enter_context(patch.object(self.manager.subprocess, "Popen"))
        self.popen.return_value.poll.return_value = None
        self.processes = self.stack.enter_context(patch.object(self.manager.psutil, 'process_iter', return_value=[]))

    def cleanup_workspace(self):
        # Check the resolved recursive-cleanup target before TemporaryDirectory removes it.
        self.assertTrue(self.work.is_relative_to(TEST_ROOT.resolve()))
        self.assertNotEqual(self.work, TEST_ROOT.resolve())
        self.temp.cleanup()

    def make_runtime(self):
        self.runtime.parent.mkdir(parents=True)
        self.runtime.write_bytes(b"M1 test fixture; never executed")

    def make_profiles(self):
        self.data.mkdir(parents=True)
        return self.manager.ProfileManager()

    def make_launch_profile(self, pid='Profile 1'):
        self.data.mkdir(parents=True, exist_ok=True)
        profiles = self.manager.ProfileManager()
        state = profiles.local_state.load()
        profiles._initialize_profile_structure(pid)
        state['profile']['info_cache'][pid] = {'name': pid}
        profiles.local_state.save(state)
        return profiles.get_profile_dir(pid)

    def make_autofill_source(self):
        source = self.manager.EXT_DIR
        source.mkdir(parents=True)
        (source / "manifest.json").write_text('{"manifest_version": 3}', encoding="utf-8")
        (source / "config.js").write_text(
            'const ACCOUNT = {email: "", password: "", totpSecret: ""};', encoding="utf-8"
        )

    def test_paths_do_not_depend_on_working_directory(self):
        previous = Path.cwd()
        try:
            os.chdir(self.work)
            module = load_manager()
        finally:
            os.chdir(previous)
        self.assertEqual(module.PROJECT_ROOT, PROJECT_ROOT)
        self.assertEqual(module.BROWSER_EXE, PROJECT_ROOT / "browser" / "chrome.exe")
        self.assertEqual(module.DATA_DIR, PROJECT_ROOT / "legacy" / "data")
        self.assertEqual(module.PROFILES_DIR, PROJECT_ROOT / "profiles")
        self.assertEqual(module.CONFIG_DIR, PROJECT_ROOT / "config")
        self.assertEqual(module.PROFILES_JSON, PROJECT_ROOT / "config" / "profiles.json")
        self.assertEqual(module.LOCAL_STATE, module.DATA_DIR / "Local State")
        self.assertEqual(module.LOG_DIR, PROJECT_ROOT / "legacy" / "log")
        self.assertEqual(module.EXT_DIR, PROJECT_ROOT / "extensions" / "discord-autofill-extension")
        self.assertEqual(module.TOKEN_EXT_DIR.parent, PROJECT_ROOT / "extensions")

    def test_project_path_with_spaces_and_unicode(self):
        project = self.work / "Project with spaces Thử nghiệm"
        module = load_manager(project / "legacy" / "profile_manager.py")
        self.assertEqual(module.BROWSER_EXE, project / "browser" / "chrome.exe")
        self.assertEqual(module.PROFILES_DIR, project / "profiles")
        self.assertEqual(module.LOCAL_STATE, project / "legacy" / "data" / "Local State")

    def test_direct_launch_preserves_arguments(self):
        self.make_runtime()
        self.make_launch_profile()
        self.manager.ChromiumLauncher().launch_discord("Profile 1")
        command = self.popen.call_args.args[0]
        self.assertEqual(command, [
            str(self.runtime),
            f"--user-data-dir={self.data / 'Profile 1'}",
            "--new-window", "--no-first-run", "--no-default-browser-check",
            "--disable-sync", "--process-per-site", "https://discord.com/app",
        ])
        self.assertEqual(self.popen.call_args.kwargs, {
            "shell": False,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "creationflags": subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        })

    def test_profiles_keep_distinct_user_data_roots(self):
        self.make_runtime()
        launcher = self.manager.ChromiumLauncher()
        for profile_id in ("Profile 1", "Profile 2"):
            self.make_launch_profile(profile_id)
            launcher.launch_discord(profile_id)
        roots = [call.args[0][1] for call in self.popen.call_args_list]
        self.assertEqual(roots, [f"--user-data-dir={self.data / pid}" for pid in ("Profile 1", "Profile 2")])

    def test_extension_arguments_preserve_multiple_paths(self):
        self.make_runtime()
        profile = self.make_launch_profile()
        extensions = [profile / "First extension", profile / "Second extension"]
        for extension in extensions:
            extension.mkdir()
        self.manager.ChromiumLauncher().launch_discord("Profile 1", [None, *extensions, self.work / "missing"])
        joined = ",".join(map(str, extensions))
        self.assertEqual(self.popen.call_args.args[0][-2:], [
            f"--disable-extensions-except={joined}", f"--load-extension={joined}"
        ])

    def test_missing_optional_extensions_do_not_block_launch(self):
        self.make_runtime()
        self.make_launch_profile()
        self.manager.ChromiumLauncher().launch_discord("Profile 1", [None, self.work / "missing"])
        self.assertFalse(any(arg.startswith("--load-extension=") for arg in self.popen.call_args.args[0]))

    def test_missing_runtime_reports_expected_path_without_launch(self):
        with self.assertRaises(self.manager.ProfileManagerError) as error:
            self.manager.ChromiumLauncher().launch_discord("Profile 1")
        self.assertIn(str(self.runtime), str(error.exception))
        self.assertIn("Expected executable", str(error.exception))
        self.popen.assert_not_called()

    def test_directory_named_chrome_exe_is_not_a_runtime(self):
        self.runtime.mkdir(parents=True)
        with self.assertRaises(self.manager.ProfileManagerError):
            self.manager.ChromiumLauncher().launch_discord("Profile 1")
        self.popen.assert_not_called()

    def test_process_start_failure_remains_an_application_error(self):
        self.make_runtime()
        self.make_launch_profile()
        self.popen.side_effect = OSError("Synthetic process start failure")
        with self.assertRaisesRegex(self.manager.ProfileManagerError, "Cannot launch Chromium"):
            self.manager.ChromiumLauncher().launch_discord("Profile 1")

    def test_missing_runtime_at_startup_shows_dialog_and_returns(self):
        with patch.object(self.manager.tk, "Tk") as tk_root, \
                patch.object(self.manager.messagebox, "showerror") as showerror, \
                patch.object(self.manager, "ProfileManagerApp") as app, \
                patch("builtins.input") as console_input:
            self.assertIsNone(self.manager.main())
        tk_root.return_value.withdraw.assert_called_once()
        tk_root.return_value.destroy.assert_called_once()
        showerror.assert_called_once()
        self.assertIn(str(self.runtime), showerror.call_args.args[1])
        self.assertEqual(showerror.call_args.kwargs["parent"], tk_root.return_value)
        app.assert_not_called()
        console_input.assert_not_called()
        self.popen.assert_not_called()
        self.assertFalse(self.data.exists())

    def test_present_runtime_starts_existing_gui_and_preserves_registry(self):
        self.make_runtime()
        self.data.mkdir(parents=True)
        original = b'{"profile":{"info_cache":{}},"custom":"preserve exactly"}'
        self.manager.LOCAL_STATE.write_bytes(original)
        with patch.object(self.manager.tk, "Tk") as tk_root, \
                patch.object(self.manager.messagebox, "showerror") as showerror, \
                patch.object(self.manager, "ProfileManagerApp") as app:
            self.manager.main()
        app.assert_called_once_with(tk_root.return_value)
        tk_root.return_value.mainloop.assert_called_once()
        showerror.assert_not_called()
        self.assertEqual(self.manager.LOCAL_STATE.read_bytes(), original)

    def test_fresh_start_keeps_existing_local_state_format(self):
        self.make_runtime()
        with patch.object(self.manager.tk, "Tk"), patch.object(self.manager, "ProfileManagerApp"):
            self.manager.main()
        self.assertEqual(json.loads(self.manager.LOCAL_STATE.read_text()), {"profile": {"info_cache": {}}})

    def test_runtime_missing_after_startup_uses_existing_gui_error(self):
        app = self.manager.ProfileManagerApp.__new__(self.manager.ProfileManagerApp)
        app.get_selected_profiles = Mock(return_value=[("Profile 1", "M1 Test")])
        app.profile_manager = self.manager.ProfileManager()
        app.launcher = self.manager.ChromiumLauncher()
        app.update_status = Mock()
        with patch.object(self.manager.messagebox, "showerror") as showerror:
            app.open_discord()
        self.assertIn(str(self.runtime), showerror.call_args.args[1])
        self.popen.assert_not_called()

    def test_profile_create_rename_delete_and_restart_preserve_existing_data(self):
        profiles = self.make_profiles()
        existing = profiles.create_profile("Existing synthetic profile")
        sentinel = profiles.get_profile_dir(existing) / "existing-session.fixture"
        sentinel.write_bytes(b"synthetic session bytes")
        state = profiles.local_state.load()
        state["unknown_browser_state"] = {"keep": True}
        profiles.local_state.save(state)
        created = profiles.create_profile("M1 Test")
        directory = profiles.get_profile_dir(created)
        profiles.rename_profile(created, "M1 Renamed")
        restarted = self.manager.ProfileManager()
        self.assertIn((created, "M1 Renamed"), restarted.get_profiles())
        self.assertTrue(directory.is_dir())
        self.assertTrue(directory.resolve().is_relative_to(self.work))
        restarted.delete_profile(created)
        self.assertFalse(directory.exists())
        self.assertEqual(sentinel.read_bytes(), b"synthetic session bytes")
        self.assertEqual(restarted.local_state.load()["unknown_browser_state"], {"keep": True})
        self.assertEqual(restarted.get_profiles(), [(existing, "Existing synthetic profile")])

    def test_account_storage_and_existing_extension_copy_are_preserved(self):
        self.make_autofill_source()
        profiles = self.make_profiles()
        pid = profiles.create_profile("Synthetic account")
        accounts = self.manager.AccountManager(profiles)
        accounts.set_account(pid, "m1@example.invalid:synthetic-password")
        expected = {"email": "m1@example.invalid", "password": "synthetic-password", "totp_secret": ""}
        self.assertEqual(self.manager.AccountManager(self.manager.ProfileManager()).get_account(pid), expected)
        config = accounts._get_config_path(pid)
        original = config.read_bytes()
        accounts._ensure_both_extensions_installed(pid)
        self.assertEqual(config.read_bytes(), original)
        accounts.remove_account(pid)
        self.assertIsNone(accounts.get_account(pid))

    def test_txt_import_preserves_account_workflow(self):
        self.make_autofill_source()
        profiles = self.make_profiles()
        import_file = self.work / "synthetic-accounts.txt"
        import_file.write_text(
            "m1-one@example.invalid:synthetic-one\nm1-two@example.invalid:synthetic-two\n", encoding="utf-8"
        )
        app = self.manager.ProfileManagerApp.__new__(self.manager.ProfileManagerApp)
        app.profile_manager = profiles
        app.account_manager = self.manager.AccountManager(profiles)
        app.profiles = []
        app.refresh_list = Mock()
        with patch.object(self.manager.filedialog, "askopenfilename", return_value=str(import_file)), \
                patch.object(self.manager.messagebox, "showinfo"), \
                patch.object(self.manager.messagebox, "showerror") as showerror:
            app.bulk_import_profiles()
        showerror.assert_not_called()
        imported = profiles.get_profiles()
        self.assertEqual([name for _, name in imported], ["0001 | m1-one", "0002 | m1-two"])
        self.assertEqual([app.account_manager.get_account(pid)["email"] for pid, _ in imported],
                         ["m1-one@example.invalid", "m1-two@example.invalid"])

    def test_gui_launch_collects_existing_profile_extension_copies(self):
        self.make_runtime()
        self.make_autofill_source()
        # An inert optional-extension fixture; no real extension code is executed.
        self.manager.TOKEN_EXT_DIR.mkdir(parents=True)
        (self.manager.TOKEN_EXT_DIR / "manifest.json").write_text('{"manifest_version": 3}', encoding="utf-8")
        profiles = self.make_profiles()
        pid = profiles.create_profile("Extension test")
        accounts = self.manager.AccountManager(profiles)
        installed = accounts._ensure_both_extensions_installed(pid)
        app = self.manager.ProfileManagerApp.__new__(self.manager.ProfileManagerApp)
        app.get_selected_profiles = Mock(return_value=[(pid, "Extension test")])
        app.profile_manager = profiles
        app.launcher = self.manager.ChromiumLauncher()
        app.update_status = Mock()
        with patch.object(self.manager.messagebox, "showerror") as showerror:
            app.open_discord()
        showerror.assert_not_called()
        self.assertEqual(len(installed), 2)
        self.assertEqual(self.popen.call_args.args[0][-1], "--load-extension=" + ",".join(map(str, installed)))

    @unittest.skipUnless(sys.platform == "win32", "Native Windows argument parsing")
    def test_windows_argument_round_trip_with_spaces_and_unicode(self):
        self.make_runtime()
        profile = self.make_launch_profile("Profile Thử nghiệm 1")
        extension = profile / "Extension with spaces Thử nghiệm"
        extension.mkdir()
        self.manager.ChromiumLauncher().launch_discord("Profile Thử nghiệm 1", [extension])
        command = self.popen.call_args.args[0]
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        split = shell32.CommandLineToArgvW
        split.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        split.restype = ctypes.POINTER(ctypes.c_wchar_p)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        count = ctypes.c_int()
        argv = split(subprocess.list2cmdline(command), ctypes.byref(count))
        self.assertTrue(argv)
        try:
            self.assertEqual([argv[i] for i in range(count.value)], command)
        finally:
            kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


if __name__ == "__main__":
    unittest.main()
