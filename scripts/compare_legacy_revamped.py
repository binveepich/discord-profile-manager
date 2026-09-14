"""Safe synthetic comparison harness for the parallel refactor.

Only deterministic, disposable-input categories are enabled. The script never
opens live application data, launches Chromium, or prints fixture contents.
"""

from pathlib import Path
import logging
import sys
import tempfile
import types
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from revamped import core


CATEGORIES = (
    "VALIDATION",
    "PATH POLICY",
    "ENVIRONMENT",
    "PROXY",
    "METADATA",
    "STORAGE",
    "LAUNCH ARGUMENTS",
    "PROFILE LIFECYCLE",
    "GUI MODEL",
)


def main():
    results = {category: None for category in CATEGORIES}
    try:
        results["VALIDATION"] = _compare_validation()
        results["PATH POLICY"] = _compare_path_policy()
    except Exception:
        # A comparison failure is reported as FAIL, without exposing paths or
        # exception text that might contain local data.
        results["VALIDATION"] = False
        results["PATH POLICY"] = False

    for category in CATEGORIES:
        result = results[category]
        label = "NOT IMPLEMENTED" if result is None else ("PASS" if result else "FAIL")
        print(f"{category}: {label}")
    implemented = [result for result in results.values() if result is not None]
    if any(result is False for result in implemented):
        print("LEGACY/REVAMPED PARITY: FAIL")
        return 1
    if any(result is None for result in results.values()):
        print("LEGACY/REVAMPED PARITY: NOT IMPLEMENTED")
    else:
        print("LEGACY/REVAMPED PARITY: PASS")
    return 0


def _load_legacy():
    source_path = PROJECT_ROOT / "legacy" / "profile_manager.py"
    module = types.ModuleType("legacy_compare_reference")
    module.__file__ = str(source_path)
    source = source_path.read_text(encoding="utf-8")
    with patch.object(Path, "mkdir"), patch.object(logging, "FileHandler"), patch.object(
        logging, "basicConfig"
    ):
        exec(compile(source, str(source_path), "exec"), module.__dict__)
    return module


def _outcome(function, *args):
    try:
        return ("value", function(*args))
    except Exception as error:
        return ("error", type(error).__name__)


def _compare_validation():
    legacy = _load_legacy()
    values = [
        "Default", "Profile 1", "profile_0001", "á thử nghiệm", "", " ",
        "..", "CON", "a/b", "C:relative", ".deleting-profile_0001",
    ]
    for value in values:
        if _outcome(legacy.validate_profile_id, value)[0] != _outcome(
            core.validate_profile_id, value
        )[0]:
            return False
    manager_paths = ["profile_0001", "profile_x", "../outside", "Profile 1"]
    for value in manager_paths:
        if _outcome(legacy.validate_manager_path, value)[0] != _outcome(
            core.validate_manager_path, value
        )[0]:
            return False
    return True


def _compare_path_policy():
    legacy = _load_legacy()
    tmp_root = PROJECT_ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="compare-", dir=tmp_root) as name:
        root = Path(name).resolve()
        paths = core.ProjectPaths(root)
        managed = paths.profiles_dir / "profile_0001"
        legacy_roots = {
            "PROFILES_DIR": paths.profiles_dir,
            "DATA_DIR": paths.data_dir,
            "PROJECT_ROOT": paths.root,
            "LOCAL_STATE": paths.local_state,
            "PROFILES_JSON": paths.profiles_json,
            "CONFIG_DIR": paths.config_dir,
        }
        with patch.multiple(legacy, **legacy_roots):
            legacy_serialized = _outcome(legacy.metadata_path_for_profile, managed)
            legacy_resolved = _outcome(
                legacy.profile_path_from_metadata, "profiles/profile_0001"
            )
        revamped_serialized = _outcome(core.metadata_path_for_profile, managed, paths)
        revamped_resolved = _outcome(
            core.profile_path_from_metadata, "profiles/profile_0001", paths
        )
        return legacy_serialized == revamped_serialized and legacy_resolved == revamped_resolved


if __name__ == "__main__":
    raise SystemExit(main())
