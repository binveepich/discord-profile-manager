"""Low-level paths, validation, and safety policy for the revamped app."""

from dataclasses import dataclass
import os
from pathlib import Path, PureWindowsPath
import re
import stat


NEW_PROFILE_PATTERN = re.compile(r"^profile_(\d+)$", re.IGNORECASE)
MANAGER_PATH_KEY = "manager_path"


class ProfileManagerError(Exception):
    """Base category for safe profile-manager failures."""


class ProfileNotFoundError(ProfileManagerError):
    """A requested profile is not registered or its data is unavailable."""


class ExtensionError(ProfileManagerError):
    """Base category for extension discovery/deployment failures."""


class ExtensionNotFoundError(ExtensionError):
    """The supported extension source is not available."""


class ExtensionDeploymentError(ExtensionError):
    """An extension deployment could not be completed safely."""


class InvalidAccountFormatError(ProfileManagerError):
    """A legacy-compatible account string is malformed."""


class ProxyValidationError(ProfileManagerError):
    """A proxy value is outside the supported unauthenticated policy."""


@dataclass(frozen=True)
class ProjectPaths:
    """Separate writable state paths from repository-owned read-only assets.

    Constructing this value performs no filesystem access. Services decide when
    to create or inspect their own directories.
    """

    root: Path
    assets_root: Path | None = None

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).absolute())
        object.__setattr__(
            self,
            "assets_root",
            Path(self.assets_root if self.assets_root is not None else self.root).absolute(),
        )

    @property
    def project_root(self):
        return self.assets_root

    @property
    def browser_exe(self):
        return self.assets_root / "browser" / "chrome.exe"

    @property
    def config_dir(self):
        return self.root / "config"

    @property
    def profiles_json(self):
        return self.config_dir / "profiles.json"

    @property
    def extension_policy_json(self):
        """Application-owned global extension enablement policy."""
        return self.config_dir / "extensions.json"

    # Keep the shorter name available to callers that treat the file as the
    # global extension registry policy rather than as profile metadata.
    @property
    def extensions_json(self):
        return self.extension_policy_json

    @property
    def data_dir(self):
        return self.root / "data"

    @property
    def local_state(self):
        return self.data_dir / "Local State"

    @property
    def profiles_dir(self):
        return self.root / "profiles"

    @property
    def log_dir(self):
        return self.root / "logs"

    @property
    def legacy_log_dir(self):
        return self.root / "logs"

    @property
    def extensions_dir(self):
        return self.assets_root / "extensions"

    @property
    def autofill_extension_dir(self):
        return self.extensions_dir / "discord-autofill-extension"

    @property
    def token_extractor_extension_dir(self):
        return self.extensions_dir / "discord-token-extractor-extension"


def validate_profile_id(profile_id):
    """Reject Windows path aliases and names that can escape a profile root."""
    if (
        not isinstance(profile_id, str)
        or not profile_id
        or profile_id != profile_id.strip()
        or profile_id.endswith(".")
        or profile_id in (".", "..")
        or profile_id.startswith(".deleting-")
        or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in profile_id)
        or PureWindowsPath(profile_id).is_reserved()
    ):
        raise ProfileManagerError(
            "Invalid profile ID in metadata. Restore or correct metadata before continuing."
        )
    return profile_id


def _is_reparse_point(info):
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        reparse_point
        and getattr(info, "st_file_attributes", 0) & reparse_point
    )


def checked_path(path, root):
    """Require containment and reject links/reparse points in existing parents."""
    path = Path(path).absolute()
    root = Path(root).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ProfileManagerError("Profile path is outside its data directory.") from error

    components = [root]
    components.extend(
        root.joinpath(*relative.parts[:index])
        for index in range(1, len(relative.parts) + 1)
    )
    for item in components:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ProfileManagerError(f"Cannot inspect managed path: {item}") from error
        if _is_reparse_point(info):
            raise ProfileManagerError(f"Linked profile paths are not supported: {item}")

    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
        resolved_path.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError) as error:
        raise ProfileManagerError(
            "Profile path resolves outside its data directory."
        ) from error
    return path


def validate_manager_path(manager_path):
    """Validate a legacy managed marker such as ``profile_0001``."""
    if not isinstance(manager_path, str) or not NEW_PROFILE_PATTERN.fullmatch(manager_path):
        raise ProfileManagerError("Invalid managed profile path in metadata.")
    return manager_path


def validate_candidate_profile_name(profile_name):
    """Return false for unsafe names while scanning physical roots."""
    try:
        validate_profile_id(profile_name)
    except ProfileManagerError:
        return False
    return True


def ensure_tree_has_no_links(root):
    """Reject links/reparse points anywhere in a tree before copying it."""
    root = Path(root)
    checked_path(root, root.parent)
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for current, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            item = Path(current) / name
            try:
                info = item.lstat()
            except OSError as error:
                raise ProfileManagerError(f"Cannot inspect linked profile data: {item}") from error
            if stat.S_ISLNK(info.st_mode) or bool(
                reparse_point
                and getattr(info, "st_file_attributes", 0) & reparse_point
            ):
                raise ProfileManagerError(f"Linked profile data cannot be migrated: {item}")


def metadata_path_for_profile(path, paths):
    """Serialize a profile below ``profiles/`` or ``data/`` safely."""
    path = Path(path).absolute()
    roots = (
        (Path(paths.profiles_dir).absolute(), ("profiles",)),
        (Path(paths.data_dir).absolute(), ("data",)),
    )
    for root, prefix in roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if not relative.parts:
            raise ProfileManagerError("A profile directory must be below its profile root.")
        checked_path(path, root)
        return "/".join((*prefix, *relative.parts))
    raise ProfileManagerError("Profile directory is outside the managed profile roots.")


def profile_path_from_metadata(value, paths):
    """Resolve a serialized profile path without accepting traversal or links."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProfileManagerError("Invalid profile_directory in application metadata.")
    windows_path = PureWindowsPath(value.replace("/", "\\"))
    if (
        windows_path.is_absolute()
        or windows_path.drive
        or any(part in ("", ".", "..") for part in windows_path.parts)
    ):
        raise ProfileManagerError("Invalid profile_directory in application metadata.")
    parts = windows_path.parts
    folded_parts = tuple(part.casefold() for part in parts)
    if folded_parts[:1] == ("profiles",) and len(parts) > 1:
        root, relative_parts = Path(paths.profiles_dir), parts[1:]
    elif folded_parts[:1] == ("data",) and len(parts) > 1:
        root, relative_parts = Path(paths.data_dir), parts[1:]
    else:
        raise ProfileManagerError(
            "Profile directory must be under profiles/ or data/."
        )
    return checked_path(root.joinpath(*relative_parts), root)
