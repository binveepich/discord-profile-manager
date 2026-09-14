"""Validated staged per-profile extension deployment."""

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


AUTOFILL_EXTENSION_NAME = "discord-autofill-extension"
PROFILE_EXTENSIONS_DIR_NAME = "Unpacked Extensions"


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    info = debug
    warning = debug
    error = debug


class ExtensionService:
    """Discover and safely deploy the one supported unpacked extension."""

    def __init__(self, paths, profile_service, logger=None):
        self.paths = paths
        self.profile_service = profile_service
        self.logger = logger or _NullLogger()

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
    def _validate_extension_directory(cls, extension_dir, description):
        extension_dir = Path(extension_dir)
        if not extension_dir.is_dir():
            raise ExtensionError(f"{description} is not a directory.")
        try:
            ensure_tree_has_no_links(extension_dir)
        except ProfileManagerError as error:
            raise ExtensionError(f"{description} contains an unsupported linked path.") from error
        manifest_file = extension_dir / "manifest.json"
        config_file = extension_dir / "config.js"
        if not manifest_file.is_file():
            raise ExtensionError(f"{description} is incomplete: manifest.json is missing.")
        if not config_file.is_file():
            raise ExtensionError(f"{description} is incomplete: config.js is missing.")
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise ExtensionError(f"{description} has an unreadable manifest.json.") from error
        if not isinstance(manifest, dict) or manifest.get("manifest_version") != 3:
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
        icons = manifest.get("icons", {})
        if icons is not None:
            if not isinstance(icons, dict):
                raise ExtensionError(f"{description} has an invalid icons section.")
            for relative_name in icons.values():
                cls._declared_file(extension_dir, relative_name, description)
        return manifest

    def get_source_path(self):
        return Path(self.paths.autofill_extension_dir)

    def discover_sources(self):
        source = self.get_source_path()
        if not source.exists():
            return {}
        checked_path(source, self.paths.extensions_dir)
        self._validate_extension_directory(source, "Autofill extension source")
        return {AUTOFILL_EXTENSION_NAME: source}

    discover = discover_sources

    def profile_extension_path(self, profile_id):
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        extensions_dir = self._profile_extensions_dir(profile_dir)
        return checked_path(
            extensions_dir / AUTOFILL_EXTENSION_NAME, profile_dir
        )

    def get_profile_extension_paths(self, profile_id):
        profile_dir = self.profile_service.get_profile_dir(profile_id)
        if not profile_dir.is_dir():
            return []
        target = checked_path(
            self._profile_extensions_dir(profile_dir) / AUTOFILL_EXTENSION_NAME,
            profile_dir,
        )
        if not target.exists():
            return []
        try:
            self._validate_extension_directory(
                target, f"Profile {profile_id} extension deployment"
            )
        except ExtensionError as error:
            self.logger.warning(
                "Skipping invalid optional extension deployment for profile %s", profile_id
            )
            return []
        return [target]

    @staticmethod
    def _remove_path(path):
        path = Path(path)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()

    def ensure_profile_extension(self, profile_id):
        """Deploy source through a stage while preserving local config/extra files."""
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        source = self.get_source_path()
        if not source.exists():
            raise ExtensionNotFoundError(f"Autofill extension source not found at {source}")
        self._validate_extension_directory(source, "Autofill extension source")
        extensions_dir = self._profile_extensions_dir(profile_dir)
        extensions_dir.mkdir(parents=True, exist_ok=True)
        target = checked_path(extensions_dir / AUTOFILL_EXTENSION_NAME, profile_dir)
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
            extensions_dir / f".{AUTOFILL_EXTENSION_NAME}.staging-{uuid.uuid4().hex}",
            profile_dir,
        )
        backup = checked_path(
            extensions_dir / f".{AUTOFILL_EXTENSION_NAME}.backup-{uuid.uuid4().hex}",
            profile_dir,
        )
        moved_to_backup = False
        try:
            shutil.copytree(source, staging)
            staged_config = checked_path(staging / "config.js", staging)
            if existing_config is not None:
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
            self._validate_extension_directory(staging, "Staged autofill extension")
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
                f"Could not deploy the autofill extension for profile {profile_id}."
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
