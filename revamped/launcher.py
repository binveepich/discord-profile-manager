"""Injected Chromium launcher and deterministic command assembly."""

from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys

from .core import ProfileManagerError, checked_path
from .environment import environment_launch_arguments, environment_runtime_notes
from .processes import ChromiumProcessInspector
from .proxy import proxy_launch_arguments


DISCORD_URL = "https://discord.com/app"
FIXED_ARGUMENTS = (
    "--new-window",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
    "--process-per-site",
)


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    warning = info
    error = info


class ChromiumLauncher:
    """Launch one isolated profile using explicitly supplied services."""

    def __init__(
        self,
        paths,
        profile_service,
        *,
        extension_service=None,
        process_inspector=None,
        process_factory=None,
        environment_argument_builder=None,
        environment_notes_builder=None,
        logger=None,
    ):
        self.paths = paths
        self.profile_service = profile_service
        self.extension_service = extension_service
        self.launcher_path = Path(paths.browser_exe)
        self.process_inspector = process_inspector or ChromiumProcessInspector()
        self.process_factory = process_factory or subprocess.Popen
        self.environment_argument_builder = (
            environment_argument_builder or environment_launch_arguments
        )
        self.environment_notes_builder = (
            environment_notes_builder or environment_runtime_notes
        )
        self.logger = logger or _NullLogger()
        self._processes = {}

    def build_environment_arguments(self, record):
        return self.environment_argument_builder(record)

    @staticmethod
    def build_proxy_arguments(record):
        return proxy_launch_arguments(record)

    def build_command(self, profile_id, profile_data_dir, profile_record, extension_paths=None):
        """Assemble a command without starting a process."""
        command = [
            str(self.launcher_path),
            f"--user-data-dir={profile_data_dir}",
            *FIXED_ARGUMENTS,
            *self.build_environment_arguments(profile_record),
            *self.build_proxy_arguments(profile_record),
            DISCORD_URL,
        ]
        if extension_paths:
            if self.extension_service is not None:
                # A caller may hold deployments from an older policy.  Keep
                # command assembly safe even when it is used directly rather
                # than through launch_discord().
                extension_paths = [
                    path for path in extension_paths
                    if path and self.extension_service.is_extension_enabled(
                        Path(path).name
                    )
                ]
            valid_paths = [
                str(checked_path(path, profile_data_dir))
                for path in extension_paths
                if path and Path(path).exists()
            ]
            if any("," in path for path in valid_paths):
                raise ProfileManagerError(
                    "Extension paths containing commas cannot be loaded safely."
                )
            if valid_paths:
                joined = ",".join(valid_paths)
                command.extend([
                    f"--disable-extensions-except={joined}",
                    f"--load-extension={joined}",
                ])
        return command

    def launch_discord(self, profile_id, extension_paths=None):
        """Launch a profile and update last-opened only after process start."""
        if not self.launcher_path.is_file():
            raise ProfileManagerError(
                f"Chromium browser runtime not found. Expected executable:\n{self.launcher_path}"
            )

        operation = getattr(self.profile_service, "operation", None)
        context = operation() if callable(operation) else nullcontext()
        with context:
            profile_data_dir = self.profile_service.require_profile_dir(profile_id)
            profile_record = self.profile_service.get_profile_record(profile_id)
            previous = self._processes.get(profile_id)
            if (previous is not None and previous.poll() is None) or self.process_inspector.using_directory(profile_data_dir):
                return False
            self.profile_service.get_browser_profile_dir(profile_id)
            if self.extension_service is not None:
                # Deployment belongs to launch preparation, independently of
                # account setup, and must never refresh a live profile.  The
                # current global policy is authoritative even when the caller
                # has stale paths from an earlier launch.
                extension_paths = self.extension_service.ensure_enabled_extensions(profile_id)
            command = self.build_command(
                profile_id, profile_data_dir, profile_record, extension_paths
            )
            for note in self.environment_notes_builder(profile_record):
                self.logger.warning("Profile %s environment: %s", profile_id, note)
            self.logger.info("Requesting Chromium launch for profile %s", profile_id)
            try:
                process = self.process_factory(
                    command,
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if process.poll() not in (None, 0):
                    raise ProfileManagerError(
                        f"Chromium exited before opening profile {profile_id}."
                    )
                self._processes[profile_id] = process
                self.profile_service.mark_profile_opened(profile_id)
                return True
            except ProfileManagerError:
                raise
            except OSError as error:
                raise ProfileManagerError(f"Cannot launch Chromium: {error}") from error

    def close_profile(self, profile_id, timeout=2.0):
        """Close a Chromium process started by this launcher, when owned.

        Processes discovered after an application restart are deliberately not
        force-killed here; the caller will report that profile as undeletable
        until the user closes it normally.
        """
        process = self._processes.get(str(profile_id))
        if process is None or process.poll() is not None:
            return False
        try:
            process.terminate()
            process.wait(timeout=max(0.1, float(timeout)))
        except (OSError, subprocess.TimeoutExpired, TimeoutError, ValueError):
            return False
        return process.poll() is not None
