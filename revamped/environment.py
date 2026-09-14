"""Deterministic M7 browser environment policy."""

from math import isfinite
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_ENVIRONMENT_PRESET = "default"
ENVIRONMENT_DESKTOP = "desktop"
ENVIRONMENT_MOBILE = "mobile"
ENVIRONMENT_CUSTOM = "custom"
SUPPORTED_ENVIRONMENT_PRESETS = (
    ENVIRONMENT_DESKTOP,
    ENVIRONMENT_MOBILE,
    ENVIRONMENT_CUSTOM,
)
MOBILE_ENVIRONMENT_DEFAULTS = {
    "viewport_width": 390,
    "viewport_height": 844,
    "device_scale_factor": 1.0,
    "language": "en-US",
    "mobile_mode": True,
    "touch_mode": True,
}
LOCALE_PATTERN = re.compile(
    r"^[A-Za-z]{2,3}(?:[-_](?:[A-Za-z]{4}|[A-Za-z]{2}|\d{3}|[A-Za-z0-9]{2,8}))*$"
)


def normalize_environment_preset(value):
    """Return a supported preset name, safely falling back to Desktop."""
    if not isinstance(value, str):
        return ENVIRONMENT_DESKTOP
    normalized = value.strip().casefold().replace("_", "-")
    if normalized in (DEFAULT_ENVIRONMENT_PRESET, ENVIRONMENT_DESKTOP):
        return ENVIRONMENT_DESKTOP
    if normalized == ENVIRONMENT_MOBILE:
        return ENVIRONMENT_MOBILE
    if normalized == ENVIRONMENT_CUSTOM:
        return ENVIRONMENT_CUSTOM
    return ENVIRONMENT_DESKTOP


def normalize_locale(value):
    """Return a safe Chromium locale or None for invalid input."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().replace("_", "-")
    if not candidate or not LOCALE_PATTERN.fullmatch(candidate):
        return None
    parts = candidate.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif len(part) == 2 and part.isalpha():
            normalized.append(part.upper())
        else:
            normalized.append(part)
    return "-".join(normalized)


def normalize_timezone(value):
    """Return a valid IANA timezone identifier; never create a launch switch."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or candidate.startswith("-") or "\\" in candidate:
        return None
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return candidate


def normalize_viewport_dimension(value, minimum, maximum):
    """Return an integer dimension inside a safe range or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[+]?[0-9]+", value.strip()):
        try:
            number = int(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if minimum <= number <= maximum else None


def normalize_scale_factor(value):
    """Return a safe device scale factor or None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number) or not 0.5 <= number <= 4.0:
        return None
    return round(number, 2)


def normalize_environment_config(config):
    """Sanitize supported custom fields without allowing launch injection."""
    if not isinstance(config, dict):
        return None

    def first_value(*names):
        for name in names:
            if name in config:
                return config[name]
        return None

    normalized = {}
    width = normalize_viewport_dimension(first_value("viewport_width", "width"), 320, 7680)
    height = normalize_viewport_dimension(first_value("viewport_height", "height"), 240, 4320)
    scale = normalize_scale_factor(first_value("device_scale_factor", "scale_factor"))
    language = normalize_locale(first_value("language", "locale"))
    timezone_name = normalize_timezone(first_value("timezone"))
    if width is not None:
        normalized["viewport_width"] = width
    if height is not None:
        normalized["viewport_height"] = height
    if scale is not None:
        normalized["device_scale_factor"] = scale
    if language is not None:
        normalized["language"] = language
    if timezone_name is not None:
        normalized["timezone"] = timezone_name
    for canonical, aliases in {
        "mobile_mode": ("mobile_mode", "mobile"),
        "touch_mode": ("touch_mode", "touch"),
    }.items():
        value = first_value(*aliases)
        if isinstance(value, bool):
            normalized[canonical] = value
    return normalized


def effective_environment(record):
    """Return a normalized, non-mutating environment for one metadata record."""
    record = record if isinstance(record, dict) else {}
    preset = normalize_environment_preset(record.get("environment_preset"))
    raw_config = record.get("environment_config")
    if preset == ENVIRONMENT_DESKTOP:
        return preset, {}
    if preset == ENVIRONMENT_MOBILE:
        config = dict(MOBILE_ENVIRONMENT_DEFAULTS)
        custom = normalize_environment_config(raw_config)
        if custom:
            for key in ("viewport_width", "viewport_height", "device_scale_factor", "language"):
                if key in custom:
                    config[key] = custom[key]
            if "timezone" in custom:
                config["timezone"] = custom["timezone"]
        config["mobile_mode"] = True
        config["touch_mode"] = True
        return preset, config
    config = normalize_environment_config(raw_config)
    if not config:
        return ENVIRONMENT_DESKTOP, {}
    return preset, config


def environment_editor_state(preset, custom_config=None):
    """Return display values and editability for the environment editor."""
    normalized_preset = normalize_environment_preset(preset)
    if normalized_preset == ENVIRONMENT_DESKTOP:
        return {
            "preset": ENVIRONMENT_DESKTOP,
            "viewport_width": "Chromium default",
            "viewport_height": "Chromium default",
            "device_scale_factor": "Chromium default",
            "language": "System / Chromium default",
            "timezone": "System default",
            "mobile_mode": False,
            "touch_mode": False,
            "editable": False,
        }
    if normalized_preset == ENVIRONMENT_MOBILE:
        return {
            "preset": ENVIRONMENT_MOBILE,
            **dict(MOBILE_ENVIRONMENT_DEFAULTS),
            "timezone": "System default",
            "editable": False,
        }
    config = normalize_environment_config(custom_config) or {}
    return {
        "preset": ENVIRONMENT_CUSTOM,
        "viewport_width": config.get("viewport_width", ""),
        "viewport_height": config.get("viewport_height", ""),
        "device_scale_factor": config.get("device_scale_factor", ""),
        "language": config.get("language", ""),
        "timezone": config.get("timezone", ""),
        "mobile_mode": bool(config.get("mobile_mode", False)),
        "touch_mode": bool(config.get("touch_mode", False)),
        "editable": True,
    }


def environment_launch_arguments(record):
    """Build safe Chromium switches for one profile's environment."""
    _, config = effective_environment(record)
    arguments = []
    width = config.get("viewport_width")
    height = config.get("viewport_height")
    if width is not None and height is not None:
        arguments.append(f"--window-size={width},{height}")
    if "device_scale_factor" in config:
        arguments.append(f"--force-device-scale-factor={config['device_scale_factor']:g}")
    if config.get("language"):
        arguments.append(f"--lang={config['language']}")
    if config.get("mobile_mode"):
        arguments.append("--use-mobile-user-agent")
    if "touch_mode" in config:
        arguments.append(
            "--touch-events=enabled" if config["touch_mode"] else "--touch-events=disabled"
        )
    return arguments
