"""Deterministic records and timestamp primitives for the revamped app."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from types import MappingProxyType

from .core import metadata_path_for_profile


METADATA_VERSION = 1
DEFAULT_ENVIRONMENT_PRESET = "default"
PROFILE_TABLE_COLUMNS = (
    "name", "account", "environment", "proxy", "status", "last_opened"
)
PROFILE_TABLE_DATA_COLUMNS = PROFILE_TABLE_COLUMNS + ("id",)


def _coerce_clock(clock):
    value = clock() if callable(clock) else clock
    if value is None:
        value = datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("clock must return a datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_timestamp(clock=None):
    """Return a timezone-aware UTC ISO timestamp with second precision."""
    return _coerce_clock(clock).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def timestamp_from_epoch(value, clock=None):
    """Convert a legacy numeric epoch, safely falling back to the current clock."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value < 0
        or not math.isfinite(value)
    ):
        return utc_timestamp(clock)
    try:
        return datetime.fromtimestamp(value, timezone.utc).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return utc_timestamp(clock)


@dataclass(frozen=True)
class ProfileRecord:
    """Internal profile record while preserving unknown safe fields."""

    profile_id: str
    display_name: str
    profile_directory: str
    created_at: str
    last_opened_at: str | None = None
    environment_preset: str = DEFAULT_ENVIRONMENT_PRESET
    environment_config: dict | None = None
    proxy_enabled: bool = False
    proxy_scheme: str | None = None
    proxy_host: str | None = None
    proxy_port: int | None = None
    extras: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_mapping(cls, value):
        known = {
            "profile_id", "display_name", "profile_directory", "created_at",
            "last_opened_at", "environment_preset", "environment_config",
            "proxy_enabled", "proxy_scheme", "proxy_host", "proxy_port",
        }
        extras = MappingProxyType({key: item for key, item in value.items() if key not in known})
        raw_config = value.get("environment_config")
        return cls(
            profile_id=value["profile_id"],
            display_name=value["display_name"],
            profile_directory=value["profile_directory"],
            created_at=value["created_at"],
            last_opened_at=value.get("last_opened_at"),
            environment_preset=value.get("environment_preset", DEFAULT_ENVIRONMENT_PRESET),
            environment_config=dict(raw_config) if isinstance(raw_config, dict) else raw_config,
            proxy_enabled=value.get("proxy_enabled", False),
            proxy_scheme=value.get("proxy_scheme"),
            proxy_host=value.get("proxy_host"),
            proxy_port=value.get("proxy_port"),
            extras=extras,
        )

    def to_mapping(self):
        result = dict(self.extras)
        result.update({
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "profile_directory": self.profile_directory,
            "created_at": self.created_at,
            "last_opened_at": self.last_opened_at,
            "environment_preset": self.environment_preset,
            "proxy_enabled": self.proxy_enabled,
        })
        if self.environment_config is not None:
            result["environment_config"] = (
                dict(self.environment_config)
                if isinstance(self.environment_config, dict)
                else self.environment_config
            )
        if self.proxy_enabled:
            result.update({
                "proxy_scheme": self.proxy_scheme,
                "proxy_host": self.proxy_host,
                "proxy_port": self.proxy_port,
            })
        return result


def new_profile_record(
    profile_id, display_name, profile_path, paths, *,
    created_at=None, last_opened_at=None, clock=None
):
    """Create the minimal application-owned record for a new profile."""
    return ProfileRecord(
        profile_id=profile_id,
        display_name=display_name,
        profile_directory=metadata_path_for_profile(profile_path, paths),
        created_at=created_at or utc_timestamp(clock),
        last_opened_at=last_opened_at,
    )


def profile_pairs(records):
    """Return legacy-compatible ``(id, display name)`` rows sorted by name."""
    pairs = [(record["profile_id"], record["display_name"]) for record in records]
    pairs.sort(key=lambda item: item[1].lower())
    return [item for item in pairs if item[0] == "Default"] + [
        item for item in pairs if item[0] != "Default"
    ]
