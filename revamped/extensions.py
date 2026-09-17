"""Validated staged per-profile extension deployment."""

from contextlib import nullcontext
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import uuid

from .core import (
    ExtensionDeploymentError,
    ExtensionError,
    ExtensionNotFoundError,
    ProfileManagerError,
    checked_path,
    ensure_tree_has_no_links,
)
from .storage import ExtensionPolicyStore


AUTOFILL_EXTENSION_NAME = "discord-autofill-extension"
TOKEN_EXTRACTOR_EXTENSION_NAME = "discord-token-extractor-extension"
REQUIRED_EXTENSION_NAMES = (
    AUTOFILL_EXTENSION_NAME,
    TOKEN_EXTRACTOR_EXTENSION_NAME,
)
PROFILE_EXTENSIONS_DIR_NAME = "Unpacked Extensions"


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    info = debug
    warning = debug
    error = debug


class ExtensionService:
    """Discover and safely deploy application-owned unpacked extensions."""

    def __init__(self, paths, profile_service, logger=None):
        self.paths = paths
        self.profile_service = profile_service
        self.logger = logger or _NullLogger()
        self.policy_store = ExtensionPolicyStore(paths, self.logger)

    @staticmethod
    def _manifest_display_name(extension_name, manifest):
        value = manifest.get("name") if isinstance(manifest, dict) else None
        return value.strip() if isinstance(value, str) and value.strip() else extension_name

    def _policy_operation(self):
        operation = getattr(self.profile_service, "operation", None)
        return operation() if callable(operation) else nullcontext()

    def _policy_enabled_names(self):
        policy = self.policy_store.load()
        names = list(policy.get("enabled_extensions", ()))
        seen = {name.casefold() for name in names}
        for required_name in REQUIRED_EXTENSION_NAMES:
            if required_name.casefold() not in seen:
                names.append(required_name)
                seen.add(required_name.casefold())
        return names

    @staticmethod
    def _profile_extensions_dir(profile_dir):
        return checked_path(
            Path(profile_dir) / PROFILE_EXTENSIONS_DIR_NAME, profile_dir
        )

    @staticmethod
    def _declared_file(extension_dir, relative_name, description):
        if not isinstance(relative_name, str) or not relative_name.strip():
            raise ExtensionError(f"{description} declares an invalid file path.")
        relative = PureWindowsPath(relative_name.replace("/", "\\"))
        if relative.is_absolute() or relative.drive or any(
            part in ("", ".", "..") for part in relative.parts
        ):
            raise ExtensionError(f"{description} declares an unsafe file path.")
        candidate = checked_path(extension_dir.joinpath(*relative.parts), extension_dir)
        if not candidate.is_file():
            raise ExtensionError(f"{description} is missing {relative_name}.")
        return candidate

    @classmethod
    def _validate_extension_directory(cls, extension_dir, description, *, require_config=False):
        extension_dir = Path(extension_dir)
        if not extension_dir.is_dir():
            raise ExtensionError(f"{description} is not a directory.")
        try:
            ensure_tree_has_no_links(extension_dir)
        except ProfileManagerError as error:
            raise ExtensionError(f"{description} contains an unsupported linked path.") from error
        manifest_file = extension_dir / "manifest.json"
        if not manifest_file.is_file():
            raise ExtensionError(f"{description} is incomplete: manifest.json is missing.")
        if require_config and not (extension_dir / "config.js").is_file():
            raise ExtensionError(f"{description} is incomplete: config.js is missing.")
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise ExtensionError(f"{description} has an unreadable manifest.json.") from error
        if not isinstance(manifest, dict) or manifest.get("manifest_version") not in (2, 3):
            raise ExtensionError(f"{description} has an unsupported manifest.json.")
        content_scripts = manifest.get("content_scripts", [])
        if not isinstance(content_scripts, list):
            raise ExtensionError(f"{description} has an invalid content_scripts section.")
        for script in content_scripts:
            if not isinstance(script, dict):
                raise ExtensionError(f"{description} has an invalid content script entry.")
            scripts = script.get("js", [])
            if not isinstance(scripts, list):
                raise ExtensionError(f"{description} has an invalid content script list.")
            for relative_name in scripts:
                cls._declared_file(extension_dir, relative_name, description)

        background = manifest.get("background")
        if isinstance(background, dict):
            service_worker = background.get("service_worker")
            if service_worker is not None:
                cls._declared_file(extension_dir, service_worker, description)
            background_scripts = background.get("scripts", [])
            if not isinstance(background_scripts, list):
                raise ExtensionError(f"{description} has an invalid background script list.")
            for relative_name in background_scripts:
                cls._declared_file(extension_dir, relative_name, description)
        icons = manifest.get("icons", {})
        if icons is not None:
            if not isinstance(icons, dict):
                raise ExtensionError(f"{description} has an invalid icons section.")
            for relative_name in icons.values():
                cls._declared_file(extension_dir, relative_name, description)

        action = manifest.get("action", manifest.get("browser_action"))
        if isinstance(action, dict):
            action_icons = action.get("default_icon", {})
            if isinstance(action_icons, str):
                action_icons = {"default": action_icons}
            if action_icons is not None:
                if not isinstance(action_icons, dict):
                    raise ExtensionError(f"{description} has an invalid action icon section.")
                for relative_name in action_icons.values():
                    cls._declared_file(extension_dir, relative_name, description)
        return manifest

    def get_source_path(self, extension_name=AUTOFILL_EXTENSION_NAME):
        return checked_path(
            Path(self.paths.extensions_dir) / extension_name,
            self.paths.extensions_dir,
        )

    def discover_sources(self):
        registry = Path(self.paths.extensions_dir)
        if not registry.exists():
            return {}
        if not registry.is_dir():
            raise ExtensionError(f"Extension registry is not a directory: {registry}")

        discovered = {}
        for source in sorted(registry.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
            if not source.is_dir():
                continue
            if not (source / "manifest.json").is_file():
                self.logger.warning("Ignoring extension directory without manifest: %s", source.name)
                continue
            try:
                self._validate_extension_directory(
                    source,
                    f"Extension source {source.name}",
                )
            except ExtensionError as error:
                if source.name in REQUIRED_EXTENSION_NAMES:
                    raise
                self.logger.warning("Ignoring invalid extension source %s", source.name)
                continue
            discovered[source.name] = source
        return discovered

    discover = discover_sources

    def get_registry_state(self):
        """Return the available registry plus the effective global policy.

        Required built-ins are represented even when their source is missing so
        the manager can keep them visibly checked and locked while reporting
        the launch-time source error separately.
        """
        sources = self.discover_sources()
        enabled = {name.casefold() for name in self._policy_enabled_names()}
        built_ins = []
        for extension_name in REQUIRED_EXTENSION_NAMES:
            source = sources.get(extension_name)
            manifest = {}
            if source is not None:
                try:
                    manifest = json.loads(
                        (source / "manifest.json").read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, ValueError):
                    # ``discover_sources`` already validated this source.  If
                    # it changes between discovery and this read, retain the
                    # locked row and let launch validation fail clearly.
                    manifest = {}
            built_ins.append({
                "name": extension_name,
                "display_name": self._manifest_display_name(extension_name, manifest),
                "path": str(source) if source is not None else None,
                "available": source is not None,
                "required": True,
                "enabled": True,
            })

        optional = []
        for extension_name, source in sources.items():
            if extension_name in REQUIRED_EXTENSION_NAMES:
                continue
            try:
                manifest = json.loads(
                    (source / "manifest.json").read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, ValueError):
                manifest = {}
            optional.append({
                "name": extension_name,
                "display_name": self._manifest_display_name(extension_name, manifest),
                "path": str(source),
                "available": True,
                "required": False,
                "enabled": extension_name.casefold() in enabled,
            })
        optional.sort(key=lambda item: (item["display_name"].casefold(), item["name"]))
        all_extensions = [*built_ins, *optional]
        return {
            "built_ins": built_ins,
            "optional": optional,
            "extensions": all_extensions,
            "policy": {
                "version": ExtensionPolicyStore.version,
                "enabled_extensions": [item["name"] for item in all_extensions if item["enabled"]],
            },
        }

    # Names used by controller/UI consumers can remain descriptive without
    # coupling them to the on-disk policy implementation.
    extension_manager_state = get_registry_state

    def discover_extensions(self):
        return list(self.get_registry_state()["extensions"])

    get_available_extensions = discover_extensions
    list_extensions = discover_extensions

    def refresh_registry(self):
        return self.get_registry_state()

    def get_global_policy(self):
        return dict(self.get_registry_state()["policy"])

    get_extension_policy = get_global_policy

    def get_enabled_extension_names(self):
        return list(self.get_global_policy().get("enabled_extensions", ()))

    def is_extension_enabled(self, extension_name):
        if not isinstance(extension_name, str):
            return False
        return extension_name.casefold() in {
            name.casefold() for name in self._policy_enabled_names()
        }

    def set_extension_enabled(self, extension_name, enabled):
        """Set one optional extension in the application-owned global policy."""
        if not isinstance(extension_name, str) or not extension_name.strip():
            raise ExtensionError("Extension name is required.")
        extension_name = extension_name.strip()
        if extension_name in REQUIRED_EXTENSION_NAMES:
            if enabled is not True:
                raise ExtensionError(
                    f"Required extension {extension_name} cannot be disabled."
                )
            return self.get_registry_state()
        if enabled is not True and enabled is not False:
            raise ExtensionError("Extension enablement must be true or false.")
        sources = self.discover_sources()
        if extension_name not in sources:
            raise ExtensionNotFoundError(
                f"Extension source not found or invalid: {extension_name}"
            )
        with self._policy_operation():
            policy = self.policy_store.load()
            names = list(policy.get("enabled_extensions", ()))
            if enabled:
                if extension_name.casefold() not in {name.casefold() for name in names}:
                    names.append(extension_name)
            else:
                names = [
                    name for name in names
                    if name.casefold() != extension_name.casefold()
                ]
            normalized = []
            seen = set()
            for name in [*REQUIRED_EXTENSION_NAMES, *names]:
                if name.casefold() not in seen:
                    normalized.append(name)
                    seen.add(name.casefold())
            self.policy_store.save({
                "version": ExtensionPolicyStore.version,
                "enabled_extensions": normalized,
            })
        return self.get_registry_state()

    def enable_extension(self, extension_name):
        return self.set_extension_enabled(extension_name, True)

    def disable_extension(self, extension_name):
        return self.set_extension_enabled(extension_name, False)

    set_global_extension_enabled = set_extension_enabled

    def profile_extension_path(self, profile_id, extension_name=AUTOFILL_EXTENSION_NAME):
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        extensions_dir = self._profile_extensions_dir(profile_dir)
        return checked_path(
            extensions_dir / extension_name, profile_dir
        )

    def get_profile_extension_paths(self, profile_id):
        profile_dir = self.profile_service.get_profile_dir(profile_id)
        if not profile_dir.is_dir():
            return []
        extensions_dir = self._profile_extensions_dir(profile_dir)
        if not extensions_dir.is_dir():
            return []
        paths = []
        for target in sorted(extensions_dir.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
            if not target.is_dir() or target.name.startswith("."):
                continue
            try:
                self._validate_extension_directory(
                    target,
                    f"Profile {profile_id} extension deployment {target.name}",
                )
            except ExtensionError:
                self.logger.warning(
                    "Skipping invalid optional extension deployment for profile %s: %s",
                    profile_id,
                    target.name,
                )
                continue
            paths.append(target)
        return paths

    @staticmethod
    def _remove_path(path):
        path = Path(path)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()

    def ensure_profile_extension(self, profile_id, extension_name=AUTOFILL_EXTENSION_NAME):
        """Deploy source through a stage while preserving local config/extra files."""
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        source = self.get_source_path(extension_name)
        if not source.exists():
            raise ExtensionNotFoundError(f"Extension source not found at {source}")
        self._validate_extension_directory(
            source,
            f"Extension source {extension_name}",
            require_config=extension_name == AUTOFILL_EXTENSION_NAME,
        )
        extensions_dir = self._profile_extensions_dir(profile_dir)
        extensions_dir.mkdir(parents=True, exist_ok=True)
        target = checked_path(extensions_dir / extension_name, profile_dir)
        if target.exists() and not target.is_dir():
            raise ExtensionDeploymentError(
                f"Profile {profile_id} extension deployment is not a directory."
            )
        existing_config = None
        if target.is_dir():
            ensure_tree_has_no_links(target)
            if (target / "config.js").is_file():
                existing_config = (target / "config.js").read_bytes()
        staging = checked_path(
            extensions_dir / f".{extension_name}.staging-{uuid.uuid4().hex}",
            profile_dir,
        )
        backup = checked_path(
            extensions_dir / f".{extension_name}.backup-{uuid.uuid4().hex}",
            profile_dir,
        )
        moved_to_backup = False
        try:
            shutil.copytree(source, staging)
            staged_config = staging / "config.js"
            if existing_config is not None:
                staged_config = checked_path(staged_config, staging)
                staged_config.write_bytes(existing_config)
            if target.is_dir():
                for current, _, files in os.walk(target, followlinks=False):
                    for name in files:
                        existing = Path(current) / name
                        relative = existing.relative_to(target)
                        if relative == Path("config.js"):
                            continue
                        destination = checked_path(staging / relative, staging)
                        if not destination.exists():
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(existing, destination)
            self._validate_extension_directory(
                staging,
                f"Staged extension {extension_name}",
                require_config=extension_name == AUTOFILL_EXTENSION_NAME,
            )
            if target.exists():
                target.replace(backup)
                moved_to_backup = True
            staging.replace(target)
            if backup.exists():
                try:
                    self._remove_path(backup)
                except OSError:
                    self.logger.warning("Old extension deployment could not be cleaned")
            return target
        except ExtensionError:
            raise
        except (OSError, shutil.Error) as error:
            raise ExtensionDeploymentError(
                f"Could not deploy extension {extension_name} for profile {profile_id}."
            ) from error
        finally:
            if staging.exists():
                try:
                    self._remove_path(staging)
                except OSError:
                    self.logger.warning("Temporary extension deployment could not be cleaned")
            if moved_to_backup and backup.exists() and not target.exists():
                try:
                    backup.replace(target)
                except OSError:
                    self.logger.error("Previous extension deployment could not be restored")

    def ensure_required_extensions(self, profile_id):
        """Deploy both product defaults or fail clearly before launching a profile.

        Account setup is not a prerequisite. The GUI/launcher calls this at the
        launch boundary, so fresh profiles receive the same built-in registry
        extensions as profiles with account metadata.
        """
        sources = self.discover_sources()
        for extension_name in REQUIRED_EXTENSION_NAMES:
            if extension_name not in sources:
                raise ExtensionNotFoundError(
                    f"Required extension source not found at {self.get_source_path(extension_name)}"
                )
        return [
            self.ensure_profile_extension(profile_id, extension_name)
            for extension_name in REQUIRED_EXTENSION_NAMES
        ]

    def ensure_enabled_extensions(self, profile_id):
        """Deploy exactly the extensions enabled by the current global policy."""
        sources = self.discover_sources()
        for extension_name in REQUIRED_EXTENSION_NAMES:
            if extension_name not in sources:
                raise ExtensionNotFoundError(
                    f"Required extension source not found at {self.get_source_path(extension_name)}"
                )

        enabled = {name.casefold() for name in self._policy_enabled_names()}
        names = list(REQUIRED_EXTENSION_NAMES)
        names.extend(
            extension_name
            for extension_name in sorted(sources, key=lambda item: (item.casefold(), item))
            if extension_name not in REQUIRED_EXTENSION_NAMES
            and extension_name.casefold() in enabled
        )
        return [
            self.ensure_profile_extension(profile_id, extension_name)
            for extension_name in names
        ]

    def get_enabled_profile_extension_paths(self, profile_id):
        """Return only current-policy deployments, excluding stale disabled ones."""
        enabled = {name.casefold() for name in self._policy_enabled_names()}
        return [
            path for path in self.get_profile_extension_paths(profile_id)
            if path.name.casefold() in enabled
        ]

    # Explicit launch-oriented naming for callers that do not need deployment.
    get_launch_extension_paths = get_enabled_profile_extension_paths


ExtensionManager = ExtensionService
