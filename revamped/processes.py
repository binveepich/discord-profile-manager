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
        return bool(self.using_directories([directory], exact=exact))

    def using_directories(self, directories, exact=False):
        """Return the requested Chromium roots currently in use.

        A profile table may contain hundreds of rows.  Walking the process
        list once per row is both redundant and, on Windows, surprisingly
        expensive because command lines may require parent-process fallback.
        Keep the single-directory API for existing callers and provide one
        shared process walk for read-only status refreshes.
        """
        targets = {}
        for directory in directories:
            resolved = Path(directory).resolve()
            targets[resolved] = resolved
        if not targets:
            return set()
        targets_by_ancestor = {}
        for target in targets:
            ancestor = target
            while True:
                targets_by_ancestor.setdefault(ancestor, set()).add(target)
                if ancestor.parent == ancestor:
                    break
                ancestor = ancestor.parent
        found = set()
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
                        if exact:
                            if candidate in targets:
                                found.add(candidate)
                            continue
                        # Candidate is a shared ancestor of one or more
                        # requested roots, or a requested root is an ancestor
                        # of the candidate.  Both checks are path-indexed and
                        # avoid comparing every process with every profile.
                        found.update(targets_by_ancestor.get(candidate, ()))
                        ancestor = candidate
                        while ancestor != ancestor.parent:
                            if ancestor in targets:
                                found.add(ancestor)
                            ancestor = ancestor.parent
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
        return found

    __call__ = using_directory
