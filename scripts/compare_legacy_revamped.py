"""Safe synthetic comparison harness for the parallel refactor.

Only deterministic, disposable-input categories are enabled. The script never
opens live application data, launches Chromium, or prints fixture contents.
"""

from pathlib import Path
import logging
import sys
import tempfile
import types
from contextlib import contextmanager
from unittest.mock import Mock
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from revamped import core, environment, proxy
from revamped.profiles import ProfileService
from revamped.processes import ChromiumProcessInspector
from revamped.storage import LegacyStateStore


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
        results["ENVIRONMENT"] = _compare_environment()
        results["PROXY"] = _compare_proxy()
        results["LAUNCH ARGUMENTS"] = _compare_launch_arguments()
        results["PROFILE LIFECYCLE"] = _compare_profile_lifecycle()
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


def _compare_environment():
    legacy = _load_legacy()
    records = [
        {},
        {"environment_preset": "default"},
        {"environment_preset": "mobile"},
        {"environment_preset": "custom", "environment_config": {"width": 1200, "height": 800, "scale_factor": 1.5, "language": "en-US", "mobile_mode": True, "touch_mode": False, "timezone": "UTC"}},
        {"environment_preset": "custom", "environment_config": ["broken"]},
    ]
    for record in records:
        if environment.effective_environment(record) != legacy.effective_environment(record):
            return False
        if environment.environment_launch_arguments(record) != legacy.environment_launch_arguments(record):
            return False
    return True


def _compare_proxy():
    legacy = _load_legacy()
    records = [
        {"proxy_enabled": False},
        {"proxy_enabled": True, "proxy_scheme": "https", "proxy_host": "proxy.example", "proxy_port": 443},
        {"proxy_enabled": True, "proxy_scheme": "socks5", "proxy_host": "2001:db8::1", "proxy_port": 1080},
        {"proxy_enabled": True, "proxy_scheme": "unknown", "proxy_host": "bad host", "proxy_port": []},
    ]
    for record in records:
        if proxy.effective_proxy(record) != legacy.effective_proxy(record):
            return False
        if proxy.proxy_launch_arguments(record) != legacy.proxy_launch_arguments(record):
            return False
    for value in (
        "proxy.example:8080",
        "socks5://proxy.example:1080",
        "https://user:password@secure-proxy.example:443",
        "proxy.example:8080:user:pa:ss",
    ):
        if proxy.parse_proxy_string(value) != legacy.parse_proxy_string(value):
            return False
    return True


def _compare_launch_arguments():
    legacy = _load_legacy()
    with tempfile.TemporaryDirectory(prefix="compare-launch-", dir=PROJECT_ROOT / "tmp") as name:
        root = Path(name).resolve()
        paths = core.ProjectPaths(root)
        paths.browser_exe.parent.mkdir(parents=True)
        paths.browser_exe.write_bytes(b"synthetic runtime")
        for attribute, value in {
            "PROJECT_ROOT": paths.root,
            "BROWSER_EXE": paths.browser_exe,
            "DATA_DIR": paths.data_dir,
            "PROFILES_DIR": paths.profiles_dir,
            "CONFIG_DIR": paths.config_dir,
            "PROFILES_JSON": paths.profiles_json,
            "LOCAL_STATE": paths.local_state,
            "EXT_DIR": paths.autofill_extension_dir,
        }.items():
            setattr(legacy, attribute, value)
        legacy_popen = Mock()
        legacy_popen.return_value.poll.return_value = None
        with patch.object(legacy.subprocess, "Popen", legacy_popen), patch.object(
            legacy.psutil, "process_iter", return_value=[]
        ):
            profile_id = legacy.ProfileManager().create_profile("Compare")
            legacy.ChromiumLauncher().launch_discord(profile_id)
            legacy_command = legacy_popen.call_args.args[0]

        profile_path = paths.profiles_dir / profile_id

        class Service:
            def __init__(self):
                self.record = {"profile_id": profile_id, "proxy_enabled": False}

            @contextmanager
            def operation(self):
                yield

            def require_profile_dir(self, requested):
                if requested != profile_id:
                    raise ValueError("missing synthetic profile")
                return profile_path

            def get_profile_record(self, requested):
                return dict(self.record)

            def get_browser_profile_dir(self, requested):
                return profile_path / "Default"

            def mark_profile_opened(self, requested):
                pass

        revamped_popen = Mock()
        revamped_popen.return_value.poll.return_value = None
        revamped = __import__("revamped.launcher", fromlist=["ChromiumLauncher"]).ChromiumLauncher(
            paths,
            Service(),
            process_inspector=__import__("revamped.processes", fromlist=["ChromiumProcessInspector"]).ChromiumProcessInspector(
                process_iter=lambda *_: []
            ),
            process_factory=revamped_popen,
        )
        revamped.launch_discord(profile_id)
        return legacy_command == revamped_popen.call_args.args[0]


def _configure_legacy_paths(legacy, paths):
    for attribute, value in {
        "PROJECT_ROOT": paths.root,
        "BROWSER_EXE": paths.browser_exe,
        "DATA_DIR": paths.data_dir,
        "PROFILES_DIR": paths.profiles_dir,
        "CONFIG_DIR": paths.config_dir,
        "PROFILES_JSON": paths.profiles_json,
        "LOCAL_STATE": paths.local_state,
        "LOG_DIR": paths.legacy_log_dir,
        "EXTENSIONS_DIR": paths.extensions_dir,
        "EXT_DIR": paths.autofill_extension_dir,
    }.items():
        setattr(legacy, attribute, value)


def _seed_legacy_profile(paths, store, profile_id="Legacy 1"):
    state = store.load()
    store.save(state)
    browser_profile = paths.data_dir / profile_id / "Default"
    browser_profile.mkdir(parents=True)
    (browser_profile / "Preferences").write_text(
        '{"profile": {"name": "synthetic"}}', encoding="utf-8"
    )
    state = store.load()
    state["profile"]["info_cache"][profile_id] = {"name": "Legacy", "created": 0}
    store.save(state)


def _compare_profile_lifecycle():
    with tempfile.TemporaryDirectory(prefix="compare-lifecycle-", dir=PROJECT_ROOT / "tmp") as legacy_name, tempfile.TemporaryDirectory(
        prefix="compare-lifecycle-", dir=PROJECT_ROOT / "tmp"
    ) as revamped_name:
        legacy_paths = core.ProjectPaths(Path(legacy_name))
        legacy = _load_legacy()
        _configure_legacy_paths(legacy, legacy_paths)
        with patch.object(legacy.psutil, "process_iter", return_value=[]):
            legacy_manager = legacy.ProfileManager()
            legacy_id = legacy_manager.create_profile("Compare")
            legacy_dir = legacy_manager.get_profile_dir(legacy_id)
            legacy_manager.rename_profile(legacy_id, "Renamed")
            legacy_result = (
                legacy_id,
                legacy_manager.get_profiles(),
                legacy_dir.relative_to(legacy_paths.root).as_posix(),
            )

        revamped_paths = core.ProjectPaths(Path(revamped_name))
        revamped_service = ProfileService(
            revamped_paths,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
        )
        revamped_id = revamped_service.create_profile("Compare")
        revamped_dir = revamped_service.get_profile_dir(revamped_id)
        revamped_service.rename_profile(revamped_id, "Renamed")
        revamped_result = (
            revamped_id,
            revamped_service.get_profiles(),
            revamped_dir.relative_to(revamped_paths.root).as_posix(),
        )
        if legacy_result != revamped_result:
            return False

        legacy_migration_paths = core.ProjectPaths(Path(legacy_name) / "migration")
        legacy_migration = _load_legacy()
        _configure_legacy_paths(legacy_migration, legacy_migration_paths)
        legacy_store = legacy_migration.LocalStateManager()
        _seed_legacy_profile(legacy_migration_paths, legacy_store)
        with patch.object(legacy_migration.psutil, "process_iter", return_value=[]):
            legacy_migration_id = legacy_migration.ProfileManager().migrate_profile("Legacy 1")

        revamped_migration_paths = core.ProjectPaths(Path(revamped_name) / "migration")
        revamped_store = LegacyStateStore(revamped_migration_paths)
        _seed_legacy_profile(revamped_migration_paths, revamped_store)
        revamped_migration = ProfileService(
            revamped_migration_paths,
            process_inspector=ChromiumProcessInspector(process_iter=lambda *_: []),
        )
        revamped_migration_id = revamped_migration.migrate_profile("Legacy 1")
        return (
            legacy_migration_id == revamped_migration_id
            and (legacy_migration_paths.data_dir / "Legacy 1").is_dir()
            and (revamped_migration_paths.data_dir / "Legacy 1").is_dir()
            and (legacy_migration_paths.profiles_dir / legacy_migration_id).is_dir()
            and (revamped_migration_paths.profiles_dir / revamped_migration_id).is_dir()
        )


if __name__ == "__main__":
    raise SystemExit(main())
