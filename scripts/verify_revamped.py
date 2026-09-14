"""Run the safe automated audit for the additive revamped implementation."""

import importlib
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
FROZEN_PATHS = {
    "legacy/profile_manager.py",
    "main.py",
    "tests/test_m1_runtime.py",
    "tests/test_m2_lifecycle.py",
    "tests/test_m3_migration.py",
    "tests/test_m4_metadata.py",
    "tests/test_m5_extensions.py",
    "tests/test_m6_gui.py",
    "tests/test_m7_environment.py",
    "tests/test_m8_proxy.py",
}
PROTECTED_PATH_PREFIXES = (
    "profiles/", "config/profiles.json", "legacy/data/", "legacy/log/", "logs/", "browser/",
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


def _source_tree_safety_check():
    try:
        stable_main = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        if "from legacy.profile_manager import main" not in stable_main:
            return False
        result = subprocess.run(
            ["git", "-c", "safe.directory=I:/Discord_Profile_Manager", "diff", "--name-only", "9a92bb9..HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        changed = {line.replace("\\", "/") for line in result.stdout.splitlines() if line}
        if FROZEN_PATHS.intersection(changed):
            return False
        if any(
            path.startswith(PROTECTED_PATH_PREFIXES)
            for path in changed
        ):
            return False
        if any((PROJECT_ROOT / name).exists() for name in ("Manager.exe", "Manager.spec")):
            return False
        return True
    except (OSError, UnicodeError):
        return False


def main():
    results = {
        "REVAMPED SYNTAX/IMPORT": _syntax_import_check(),
        "FROZEN LEGACY SUITE": _run(["-m", "unittest", "discover", "-s", "tests", "-p", "test_m*.py"]),
        "REVAMPED UNIT TESTS": _run(["-m", "unittest", "discover", "-s", "tests", "-p", "test_r*.py"]),
        "COMPATIBILITY TESTS": _run(["-m", "unittest", "discover", "-s", "tests", "-p", "test_*parity.py"]),
        "FREEZE INTEGRITY": _run(["scripts/check_refactor_integrity.py"]),
        "LEGACY/REVAMPED COMPARISON": _run(["scripts/compare_legacy_revamped.py"]),
        "SOURCE-TREE SAFETY": _source_tree_safety_check(),
    }
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print(f"REVAMPED AUTOMATED AUDIT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
