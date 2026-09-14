"""R5 process/launcher tests with injected process factories only."""

from contextlib import contextmanager
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

from compatibility.fixtures import DisposableWorkspace
from revamped.core import ProjectPaths, ProfileManagerError
from revamped.launcher import ChromiumLauncher
from revamped.processes import ChromiumProcessInspector


class FakeProfileService:
    def __init__(self, path, record=None):
        self.path = path
        self.record = record or {"profile_id": "profile_0001", "proxy_enabled": False}
        self.opened = []

    @contextmanager
    def operation(self):
        yield

    def require_profile_dir(self, profile_id):
        if profile_id != self.record["profile_id"]:
            raise ProfileManagerError("missing profile")
        return self.path

    def get_profile_record(self, profile_id):
        if profile_id != self.record["profile_id"]:
            raise ProfileManagerError("missing profile")
        return dict(self.record)

    def get_browser_profile_dir(self, profile_id):
        result = self.path / "Default"
        if not (result / "Preferences").is_file():
            raise ProfileManagerError("missing browser profile")
        return result

    def mark_profile_opened(self, profile_id):
        self.opened.append(profile_id)


class R5Tests(unittest.TestCase):
    def make_workspace(self):
        workspace = DisposableWorkspace("r5-")
        workspace.__enter__()
        self.addCleanup(workspace.__exit__, None, None, None)
        paths = ProjectPaths(workspace.root)
        browser = paths.browser_exe
        browser.parent.mkdir(parents=True)
        browser.write_bytes(b"synthetic runtime")
        profile = paths.profiles_dir / "profile_0001"
        (profile / "Default").mkdir(parents=True)
        (profile / "Default" / "Preferences").write_text("{}", encoding="utf-8")
        return paths, profile

    def test_process_inspector_handles_equals_and_separated_arguments(self):
        paths, profile = self.make_workspace()
        processes = []
        for args in (
            ["chrome.exe", f"--user-data-dir={profile}"],
            ["chrome.exe", "--user-data-dir", str(profile)],
        ):
            process = Mock(info={"name": "chrome.exe"})
            process.cmdline.return_value = args
            processes.append(process)
        self.assertTrue(ChromiumProcessInspector(process_iter=lambda *_: [processes[0]]).using_directory(profile))
        self.assertTrue(ChromiumProcessInspector(process_iter=lambda *_: [processes[1]]).using_directory(profile))

    def test_process_inspector_uses_parent_after_renderer_access_denied(self):
        _, profile = self.make_workspace()
        process = Mock(info={"name": "chrome.exe"})
        process.cmdline.side_effect = PermissionError("denied")
        parent = process.parent.return_value
        parent.name.return_value = "chrome.exe"
        parent.cmdline.return_value = ["chrome.exe", f"--user-data-dir={profile}"]
        inspector = ChromiumProcessInspector(process_iter=lambda *_: [process])
        # The injected module uses psutil.AccessDenied, so use the real exception
        # seam while keeping all process enumeration synthetic.
        import psutil
        process.cmdline.side_effect = psutil.AccessDenied(1)
        self.assertTrue(inspector.using_directory(profile))

    def test_process_inspector_fails_closed_on_uninspectable_process(self):
        _, profile = self.make_workspace()
        import psutil
        process = Mock(info={"name": "chrome.exe"})
        process.cmdline.side_effect = psutil.AccessDenied(1)
        process.parent.return_value = None
        with self.assertRaises(ProfileManagerError):
            ChromiumProcessInspector(process_iter=lambda *_: [process]).using_directory(profile)

    def test_launcher_builds_exact_desktop_command_without_starting_real_process(self):
        paths, profile = self.make_workspace()
        service = FakeProfileService(profile)
        factory = Mock()
        factory.return_value.poll.return_value = None
        inspector = ChromiumProcessInspector(process_iter=lambda *_: [])
        launcher = ChromiumLauncher(paths, service, process_inspector=inspector, process_factory=factory)
        self.assertTrue(launcher.launch_discord("profile_0001"))
        self.assertEqual(factory.call_args.args[0], [
            str(paths.browser_exe),
            f"--user-data-dir={profile}",
            "--new-window", "--no-first-run", "--no-default-browser-check",
            "--disable-sync", "--process-per-site", "https://discord.com/app",
        ])
        self.assertEqual(factory.call_args.kwargs["shell"], False)
        self.assertEqual(service.opened, ["profile_0001"])

    def test_launcher_keeps_environment_before_proxy_and_extensions(self):
        paths, profile = self.make_workspace()
        record = {
            "profile_id": "profile_0001",
            "environment_preset": "mobile",
            "proxy_enabled": True,
            "proxy_scheme": "http",
            "proxy_host": "proxy.example",
            "proxy_port": 8080,
        }
        service = FakeProfileService(profile, record)
        extension = profile / "extension"
        extension.mkdir()
        factory = Mock()
        factory.return_value.poll.return_value = None
        launcher = ChromiumLauncher(
            paths, service,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
            process_factory=factory,
        )
        launcher.launch_discord("profile_0001", [extension])
        command = factory.call_args.args[0]
        self.assertLess(command.index("--use-mobile-user-agent"), command.index("--proxy-server=http://proxy.example:8080"))
        self.assertEqual(command[-2:], [
            f"--disable-extensions-except={extension}",
            f"--load-extension={extension}",
        ])

    def test_missing_runtime_is_reported_before_profile_or_process_work(self):
        workspace = DisposableWorkspace("r5-missing-")
        workspace.__enter__()
        self.addCleanup(workspace.__exit__, None, None, None)
        paths = ProjectPaths(workspace.root)
        service = Mock()
        factory = Mock()
        with self.assertRaisesRegex(ProfileManagerError, "Expected executable"):
            ChromiumLauncher(paths, service, process_factory=factory).launch_discord("profile_0001")
        service.require_profile_dir.assert_not_called()
        factory.assert_not_called()

    def test_immediate_process_failure_is_reported(self):
        paths, profile = self.make_workspace()
        service = FakeProfileService(profile)
        factory = Mock()
        factory.return_value.poll.return_value = 1
        launcher = ChromiumLauncher(
            paths, service,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
            process_factory=factory,
        )
        with self.assertRaisesRegex(ProfileManagerError, "exited"):
            launcher.launch_discord("profile_0001")
        self.assertEqual(service.opened, [])


if __name__ == "__main__":
    unittest.main()

