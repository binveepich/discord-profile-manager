"""Run the safe automated audit for the additive revamped implementation.

The source-tree gate is deliberately about the current checkout.  The R0
freeze is enforced by ``check_refactor_integrity.py``; this script additionally
checks that the current working tree has not touched protected runtime or
repository-source paths.
"""

import importlib
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
PROTECTED_WORKTREE_FILES = {
    "main.py",
    "config/profiles.json",
}
PROTECTED_WORKTREE_PREFIXES = (
    "legacy/",
    "extensions/",
    "profiles/",
    "data/",
    "legacy/data/",
    "legacy/log/",
    "logs/",
    "browser/",
)
# Reviewed milestone work may touch only these explicit compatibility paths.
# Their exact content is approved by check_refactor_integrity.py; every other
# protected path remains blocked by the worktree check below.
APPROVED_MILESTONE_WORKTREE_PATHS = {
    "legacy/profile_manager.py",
    "tests/test_m5_extensions.py",
}
PROTECTED_RUNTIME_ROOTS = (
    "profiles",
    "config",
    "data",
    "legacy/data",
    "legacy/log",
    "logs",
    "browser",
)
PACKAGING_ARTIFACTS = (
    "Manager.exe",
    "Manager.spec",
    "build",
    "dist",
)
REVAMPED_MODULES = (
    "revamped",
    "revamped.core",
    "revamped.models",
    "revamped.processes",
    "revamped.environment",
    "revamped.proxy",
    "revamped.storage",
    "revamped.profiles",
    "revamped.extensions",
    "revamped.accounts",
    "revamped.launcher",
    "revamped.gui",
    "revamped.main",
    "revamped.product_api",
    "revamped.product_main",
)


def _run(arguments):
    try:
        result = subprocess.run(
            [sys.executable, "-B", *arguments],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _syntax_import_check():
    try:
        for path in sorted((PROJECT_ROOT / "revamped").rglob("*.py")):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        for module_name in REVAMPED_MODULES:
            importlib.import_module(module_name)
    except (ImportError, OSError, SyntaxError, UnicodeError):
        return False
    return True


def _git_paths(arguments):
    """Return NUL-delimited Git paths, or None when Git cannot answer."""
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={PROJECT_ROOT}", *arguments],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        output = result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return {
        path.replace("\\", "/")
        for path in output.split("\0")
        if path
    }


def _working_tree_paths():
    """Return tracked and non-ignored untracked paths changed from HEAD."""
    tracked = _git_paths(["diff", "--name-only", "-z", "HEAD", "--"])
    untracked = _git_paths(["ls-files", "--others", "--exclude-standard", "-z", "--"])
    if tracked is None or untracked is None:
        return None
    return tracked | untracked


def _is_protected_worktree_path(path):
    return (
        path in PROTECTED_WORKTREE_FILES
        or any(path.startswith(prefix) for prefix in PROTECTED_WORKTREE_PREFIXES)
    )


def _protected_runtime_snapshot(project_root=PROJECT_ROOT):
    """Snapshot protected runtime metadata without reading its file contents."""
    snapshot = []

    def raise_walk_error(error):
        raise error

    try:
        for relative_root in PROTECTED_RUNTIME_ROOTS:
            root = Path(project_root) / relative_root
            if not root.exists() and not root.is_symlink():
                snapshot.append((relative_root, "missing"))
                continue
            for current_root, directories, files in os.walk(
                root,
                topdown=True,
                followlinks=False,
                onerror=raise_walk_error,
            ):
                directories[:] = sorted(directories)
                files = sorted(files)
                current = Path(current_root)
                for name in [*directories, *files]:
                    path = current / name
                    relative = path.relative_to(Path(project_root)).as_posix()
                    stat = path.lstat()
                    snapshot.append(
                        (
                            relative,
                            stat.st_mode,
                            stat.st_size,
                            stat.st_mtime_ns,
                        )
                    )
            root_stat = root.lstat()
            snapshot.append(
                (
                    relative_root,
                    root_stat.st_mode,
                    root_stat.st_size,
                    root_stat.st_mtime_ns,
                )
            )
    except OSError:
        return None
    return tuple(sorted(snapshot))


def _source_tree_safety_check(changed_paths=None):
    try:
        stable_main = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        if "from legacy.profile_manager import main" not in stable_main:
            return False
        if not _run(["scripts/check_refactor_integrity.py"]):
            return False
        changed = _working_tree_paths() if changed_paths is None else set(changed_paths)
        if changed is None:
            return False
        blocked = {
            path
            for path in changed
            if _is_protected_worktree_path(path)
            and path not in APPROVED_MILESTONE_WORKTREE_PATHS
        }
        if blocked:
            return False
        if any((PROJECT_ROOT / name).exists() for name in PACKAGING_ARTIFACTS):
            return False
        return True
    except (OSError, UnicodeError):
        return False


def _extension_security_check():
    """Require the two product built-ins without a quarantine policy."""
    try:
        from revamped.extensions import (
            PROHIBITED_EXTENSION_NAMES,
            REQUIRED_EXTENSION_NAMES,
        )
        prohibited = {name.casefold() for name in PROHIBITED_EXTENSION_NAMES}
        required = {name.casefold() for name in REQUIRED_EXTENSION_NAMES}
        if "discord-token-extractor-extension" not in required:
            return False
        if prohibited or prohibited & required:
            return False
        if "discord-autofill-extension" not in required:
            return False
        return True
    except (ImportError, OSError, AttributeError, TypeError):
        return False


def main():
    runtime_before = _protected_runtime_snapshot()
    results = {
        "REVAMPED SYNTAX/IMPORT": _syntax_import_check(),
        "FROZEN LEGACY SUITE": _run(["-m", "unittest", "discover", "-s", "tests", "-p", "test_m*.py"]),
        "REVAMPED UNIT TESTS": _run(["-m", "unittest", "discover", "-s", "tests", "-p", "test_r*.py"]),
        "COMPATIBILITY TESTS": _run(["-m", "unittest", "discover", "-s", "tests", "-p", "test_*parity.py"]),
        "FREEZE INTEGRITY": _run(["scripts/check_refactor_integrity.py"]),
        "LEGACY/REVAMPED COMPARISON": _run(["scripts/compare_legacy_revamped.py"]),
        "PROHIBITED EXTENSION SAFETY": _extension_security_check(),
        "SOURCE-TREE SAFETY": _source_tree_safety_check(),
    }
    runtime_after = _protected_runtime_snapshot()
    results["PROTECTED RUNTIME SAFETY"] = (
        runtime_before is not None
        and runtime_before == runtime_after
    )
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print(f"REVAMPED AUTOMATED AUDIT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
