"""Injectable Chromium process inspection and user-data path matching."""

from pathlib import Path

import psutil

from .core import ProfileManagerError


CHROMIUM_PROCESS_NAMES = frozenset(("chrome.exe", "chromium.exe", "chrome", "chromium"))


def _argument_user_data_dir(args):
    """Return the raw user-data-dir argument from a process command line."""
    for index, argument in enumerate(args):
        if not isinstance(argument, str):
            continue
        if argument.startswith("--user-data-dir="):
            return argument.split("=", 1)[1]
        if argument == "--user-data-dir" and index + 1 < len(args):
            return args[index + 1]
    return None


def _candidate_directory(value, owner):
    candidate = Path(str(value).strip('"'))
    if not candidate.is_absolute():
        candidate = Path(owner.cwd()) / candidate
    return candidate.resolve()


class ChromiumProcessInspector:
    """Detect Chromium roots with an injected process iterator."""

    def __init__(self, process_iter=None, psutil_module=psutil):
        self.psutil = psutil_module
        self.process_iter = process_iter or psutil_module.process_iter

    def using_directory(self, directory, exact=False):
        directory = Path(directory).resolve()
        try:
            processes = self.process_iter(["name"])
            for process in processes:
                if (process.info.get("name") or "").lower() not in CHROMIUM_PROCESS_NAMES:
                    continue
                try:
                    owner = process
                    for _ in range(10):
                        try:
                            args = owner.cmdline()
                            break
                        except self.psutil.AccessDenied:
                            owner = owner.parent()
                            if owner is None or owner.name().lower() not in CHROMIUM_PROCESS_NAMES:
                                raise
                    else:
                        raise ProfileManagerError(
                            "Cannot identify a Chromium process's profile. Close Chromium and retry."
                        )
                    value = _argument_user_data_dir(args)
                    if value:
                        candidate = _candidate_directory(value, owner)
                        if candidate == directory or (
                            not exact
                            and (directory.is_relative_to(candidate) or candidate.is_relative_to(directory))
                        ):
                            return True
                except self.psutil.NoSuchProcess:
                    continue
                except (self.psutil.AccessDenied, OSError) as error:
                    raise ProfileManagerError(
                        "Cannot verify whether Chromium is using this profile. Close Chromium and retry."
                    ) from error
        except ProfileManagerError:
            raise
        except (self.psutil.Error, OSError) as error:
            raise ProfileManagerError(
                "Cannot check running Chromium processes. Retry after closing Chromium."
            ) from error
        return False

    __call__ = using_directory

