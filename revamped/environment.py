"""Safe, deterministic Chromium runtime-environment policy.

The original ``mobile`` preset is deliberately retained as a legacy-record
compatibility path. New Runtime Settings use the Chromium-specific presets
below instead. In particular, Android identity and browser-window geometry
are independent: Android does not inherit the legacy phone-sized window.
"""

import ctypes
from datetime import datetime
from hashlib import sha256
import locale as system_locale
from math import isfinite
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_ENVIRONMENT_PRESET = "default"
ENVIRONMENT_DESKTOP = "desktop"
ENVIRONMENT_DEFAULT_DESKTOP = "default_desktop"
# Kept only so saved pre-R11 records keep their former launch behaviour.
ENVIRONMENT_MOBILE = "mobile"
ENVIRONMENT_WINDOWS_CHROMIUM = "windows_chromium"
ENVIRONMENT_LINUX_CHROMIUM = "linux_chromium"
ENVIRONMENT_ANDROID_CHROMIUM = "android_chromium"
ENVIRONMENT_CUSTOM = "custom"
ENVIRONMENT_GENERATED = "generated"
SUPPORTED_ENVIRONMENT_PRESETS = (
    ENVIRONMENT_DESKTOP,
    ENVIRONMENT_DEFAULT_DESKTOP,
    ENVIRONMENT_MOBILE,
    ENVIRONMENT_WINDOWS_CHROMIUM,
    ENVIRONMENT_LINUX_CHROMIUM,
    ENVIRONMENT_ANDROID_CHROMIUM,
    ENVIRONMENT_CUSTOM,
    ENVIRONMENT_GENERATED,
)
RUNTIME_ENVIRONMENT_PRESETS = (
    ENVIRONMENT_DESKTOP,
    ENVIRONMENT_WINDOWS_CHROMIUM,
    ENVIRONMENT_LINUX_CHROMIUM,
    ENVIRONMENT_ANDROID_CHROMIUM,
    ENVIRONMENT_CUSTOM,
    ENVIRONMENT_GENERATED,
)
PRESET_LABELS = {
    ENVIRONMENT_DESKTOP: "Default Desktop",
    ENVIRONMENT_DEFAULT_DESKTOP: "Default Desktop",
    ENVIRONMENT_WINDOWS_CHROMIUM: "Windows Chromium",
    ENVIRONMENT_LINUX_CHROMIUM: "Linux Chromium",
    ENVIRONMENT_ANDROID_CHROMIUM: "Android Chromium",
    ENVIRONMENT_CUSTOM: "Custom",
    ENVIRONMENT_GENERATED: "Generated / Random",
    ENVIRONMENT_MOBILE: "Mobile (legacy)",
}

WINDOW_SIZE_POLICY_SYSTEM = "system"
WINDOW_SIZE_POLICY_DESKTOP = "desktop"
WINDOW_SIZE_POLICY_CUSTOM = "custom"
SUPPORTED_WINDOW_SIZE_POLICIES = (
    WINDOW_SIZE_POLICY_SYSTEM,
    WINDOW_SIZE_POLICY_DESKTOP,
    WINDOW_SIZE_POLICY_CUSTOM,
)
DESKTOP_WINDOW_DEFAULTS = {
    "viewport_width": 1280,
    "viewport_height": 800,
}

# This is intentionally unchanged for old records. It is not used by the R11
# Android Chromium preset.
MOBILE_ENVIRONMENT_DEFAULTS = {
    "viewport_width": 390,
    "viewport_height": 844,
    "device_scale_factor": 1.0,
    "language": "en-US",
    "mobile_mode": True,
    "touch_mode": True,
}

# Bundled runtime version recorded by the product audit.  Keeping this value in
# one place prevents generated identities from advertising the old R10
# Chromium 131 build while the application ships Chromium 152.
_CHROMIUM_VERSION = "152.0.7977.82"
CHROMIUM_VERSION = _CHROMIUM_VERSION

# The React/pywebview product candidate has a deliberately separate launch
# policy.  The legacy/refactor compatibility path below still retains its
# historical environment helpers, while product records opt into this marker.
# Keeping the marker in the persisted per-profile metadata makes the policy
# explicit and avoids silently rewriting older profiles during a refresh.
PRODUCT_ENVIRONMENT_SCHEMA = "product-environment-v1"
PRODUCT_WINDOW_MARGIN = 24
PRODUCT_WINDOW_GAP = 16
PRODUCT_WINDOW_MIN_WIDTH = 720
PRODUCT_WINDOW_MIN_HEIGHT = 600
PRODUCT_FALLBACK_WORK_AREA = (0, 0, 1920, 1040)

# Windows reports time zones by Windows key name while Python/Chromium-facing
# metadata uses IANA identifiers.  This compact table covers Windows' common
# regional keys (including the Vietnam/Hanoi case) without guessing a US/UTC
# setting when a system key is available.
WINDOWS_TIMEZONE_TO_IANA = {
    "Dateline Standard Time": "Etc/GMT+12",
    "UTC-11": "Etc/GMT+11",
    "Aleutian Standard Time": "America/Adak",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Alaskan Standard Time": "America/Anchorage",
    "Pacific Standard Time": "America/Los_Angeles",
    "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time": "America/Denver",
    "Central America Standard Time": "America/Guatemala",
    "Central Standard Time": "America/Chicago",
    "SA Pacific Standard Time": "America/Bogota",
    "Eastern Standard Time": "America/New_York",
    "US Eastern Standard Time": "America/Indianapolis",
    "Venezuela Standard Time": "America/Caracas",
    "Paraguay Standard Time": "America/Asuncion",
    "Atlantic Standard Time": "America/Halifax",
    "Central Brazilian Standard Time": "America/Cuiaba",
    "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago",
    "Newfoundland Standard Time": "America/St_Johns",
    "Tocantins Standard Time": "America/Araguaina",
    "E. South America Standard Time": "America/Sao_Paulo",
    "SA Eastern Standard Time": "America/Cayenne",
    "Argentina Standard Time": "America/Buenos_Aires",
    "Greenland Standard Time": "America/Nuuk",
    "Montevideo Standard Time": "America/Montevideo",
    "Magallanes Standard Time": "America/Punta_Arenas",
    "Saint Pierre Standard Time": "America/Miquelon",
    "Bahia Standard Time": "America/Bahia",
    "UTC": "UTC",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris",
    "Central European Standard Time": "Europe/Warsaw",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "Jordan Standard Time": "Asia/Amman",
    "GTB Standard Time": "Europe/Bucharest",
    "Middle East Standard Time": "Asia/Beirut",
    "Egypt Standard Time": "Africa/Cairo",
    "E. Europe Standard Time": "Europe/Chisinau",
    "Syria Standard Time": "Asia/Damascus",
    "West Bank Standard Time": "Asia/Hebron",
    "South Africa Standard Time": "Africa/Johannesburg",
    "FLE Standard Time": "Europe/Kyiv",
    "Israel Standard Time": "Asia/Jerusalem",
    "Kaliningrad Standard Time": "Europe/Kaliningrad",
    "Sudan Standard Time": "Africa/Khartoum",
    "Libya Standard Time": "Africa/Tripoli",
    "Namibia Standard Time": "Africa/Windhoek",
    "Arabic Standard Time": "Asia/Baghdad",
    "Turkey Standard Time": "Europe/Istanbul",
    "Arab Standard Time": "Asia/Riyadh",
    "Belarus Standard Time": "Europe/Minsk",
    "Russian Standard Time": "Europe/Moscow",
    "E. Africa Standard Time": "Africa/Nairobi",
    "Iran Standard Time": "Asia/Tehran",
    "Arabian Standard Time": "Asia/Dubai",
    "Astrakhan Standard Time": "Europe/Astrakhan",
    "Azerbaijan Standard Time": "Asia/Baku",
    "Russia Time Zone 3": "Europe/Samara",
    "Mauritius Standard Time": "Indian/Mauritius",
    "Saratov Standard Time": "Europe/Saratov",
    "Georgian Standard Time": "Asia/Tbilisi",
    "Caucasus Standard Time": "Asia/Yerevan",
    "Afghanistan Standard Time": "Asia/Kabul",
    "West Asia Standard Time": "Asia/Tashkent",
    "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "Pakistan Standard Time": "Asia/Karachi",
    "India Standard Time": "Asia/Kolkata",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Nepal Standard Time": "Asia/Kathmandu",
    "Central Asia Standard Time": "Asia/Bishkek",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "Omsk Standard Time": "Asia/Omsk",
    "Myanmar Standard Time": "Asia/Yangon",
    "SE Asia Standard Time": "Asia/Ho_Chi_Minh",
    "Altai Standard Time": "Asia/Barnaul",
    "W. Mongolia Standard Time": "Asia/Hovd",
    "North Asia Standard Time": "Asia/Krasnoyarsk",
    "N. Central Asia Standard Time": "Asia/Novosibirsk",
    "Tomsk Standard Time": "Asia/Tomsk",
    "China Standard Time": "Asia/Shanghai",
    "North Asia East Standard Time": "Asia/Irkutsk",
    "Singapore Standard Time": "Asia/Singapore",
    "W. Australia Standard Time": "Australia/Perth",
    "Taipei Standard Time": "Asia/Taipei",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar",
    "Aus Central W. Standard Time": "Australia/Eucla",
    "Transbaikal Standard Time": "Asia/Chita",
    "Tokyo Standard Time": "Asia/Tokyo",
    "North Korea Standard Time": "Asia/Pyongyang",
    "Korea Standard Time": "Asia/Seoul",
    "Yakutsk Standard Time": "Asia/Yakutsk",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "AUS Central Standard Time": "Australia/Darwin",
    "E. Australia Standard Time": "Australia/Brisbane",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "West Pacific Standard Time": "Pacific/Port_Moresby",
    "Tasmania Standard Time": "Australia/Hobart",
    "Vladivostok Standard Time": "Asia/Vladivostok",
    "Lord Howe Standard Time": "Australia/Lord_Howe",
    "Bougainville Standard Time": "Pacific/Bougainville",
    "Russia Time Zone 10": "Asia/Srednekolymsk",
    "Magadan Standard Time": "Asia/Magadan",
    "Norfolk Standard Time": "Pacific/Norfolk",
    "Sakhalin Standard Time": "Asia/Sakhalin",
    "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Russia Time Zone 11": "Asia/Kamchatka",
    "New Zealand Standard Time": "Pacific/Auckland",
    "UTC+12": "Etc/GMT-12",
    "Fiji Standard Time": "Pacific/Fiji",
    "Chatham Islands Standard Time": "Pacific/Chatham",
    "UTC+13": "Etc/GMT-13",
    "Tonga Standard Time": "Pacific/Tongatapu",
    "Samoa Standard Time": "Pacific/Apia",
    "Line Islands Standard Time": "Pacific/Kiritimati",
}
WINDOWS_CHROMIUM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{_CHROMIUM_VERSION} Safari/537.36"
)
LINUX_CHROMIUM_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{_CHROMIUM_VERSION} Safari/537.36"
)
ANDROID_CHROMIUM_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{_CHROMIUM_VERSION} Mobile Safari/537.36"
)


def user_agent_for_family(family, version=None):
    """Return a runtime-compatible ordinary UA for one supported family."""
    family = _normalize_generated_family(family) if "_normalize_generated_family" in globals() else family
    safe_version = str(version or CHROMIUM_VERSION).strip()
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", safe_version):
        safe_version = CHROMIUM_VERSION
    if family == ENVIRONMENT_LINUX_CHROMIUM:
        return (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{safe_version} Safari/537.36"
        )
    if family == ENVIRONMENT_ANDROID_CHROMIUM:
        return (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{safe_version} Mobile Safari/537.36"
        )
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{safe_version} Safari/537.36"
    )

PRESET_ENVIRONMENT_DEFAULTS = {
    ENVIRONMENT_WINDOWS_CHROMIUM: {
        **DESKTOP_WINDOW_DEFAULTS,
        "window_size_policy": WINDOW_SIZE_POLICY_DESKTOP,
        "user_agent": WINDOWS_CHROMIUM_USER_AGENT,
        "language": "en-US",
        "device_scale_factor": 1.0,
        "mobile_mode": False,
        "touch_mode": False,
    },
    ENVIRONMENT_LINUX_CHROMIUM: {
        **DESKTOP_WINDOW_DEFAULTS,
        "window_size_policy": WINDOW_SIZE_POLICY_DESKTOP,
        "user_agent": LINUX_CHROMIUM_USER_AGENT,
        "language": "en-US",
        "device_scale_factor": 1.0,
        "mobile_mode": False,
        "touch_mode": False,
    },
    ENVIRONMENT_ANDROID_CHROMIUM: {
        # The identity is Android, while the browser window remains usable on
        # a desktop. Do not substitute the legacy 390 x 844 mobile window.
        **DESKTOP_WINDOW_DEFAULTS,
        "window_size_policy": WINDOW_SIZE_POLICY_DESKTOP,
        "user_agent": ANDROID_CHROMIUM_USER_AGENT,
        "language": "en-US",
        "device_scale_factor": 2.75,
        "mobile_mode": True,
        "touch_mode": True,
    },
}
GENERATED_FAMILIES = (
    ENVIRONMENT_WINDOWS_CHROMIUM,
    ENVIRONMENT_LINUX_CHROMIUM,
    ENVIRONMENT_ANDROID_CHROMIUM,
)

LOCALE_PATTERN = re.compile(
    r"^[A-Za-z]{2,3}(?:[-_](?:[A-Za-z]{4}|[A-Za-z]{2}|\d{3}|[A-Za-z0-9]{2,8}))*$"
)


def _preset_key(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s_/-]+", "-", value.strip().casefold())


def normalize_environment_preset(value):
    """Return a supported preset name, safely falling back to Desktop."""
    normalized = _preset_key(value)
    if normalized in ("", DEFAULT_ENVIRONMENT_PRESET, ENVIRONMENT_DESKTOP):
        return ENVIRONMENT_DESKTOP
    if normalized == "default-desktop":
        return ENVIRONMENT_DESKTOP
    if normalized == ENVIRONMENT_MOBILE:
        return ENVIRONMENT_MOBILE
    if normalized in ("windows", "windows-chromium"):
        return ENVIRONMENT_WINDOWS_CHROMIUM
    if normalized in ("linux", "linux-chromium"):
        return ENVIRONMENT_LINUX_CHROMIUM
    if normalized in ("android", "android-chromium"):
        return ENVIRONMENT_ANDROID_CHROMIUM
    if normalized == ENVIRONMENT_CUSTOM:
        return ENVIRONMENT_CUSTOM
    if normalized in (ENVIRONMENT_GENERATED, "random", "generated-random"):
        return ENVIRONMENT_GENERATED
    return ENVIRONMENT_DESKTOP


def preset_label(value):
    """Return the user-facing label for a normalized preset."""
    return PRESET_LABELS[normalize_environment_preset(value)]


def runtime_preset_options():
    """Return R11 preset labels in the order used by Runtime Settings."""
    return tuple(PRESET_LABELS[preset] for preset in RUNTIME_ENVIRONMENT_PRESETS)


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


def _safe_metadata_text(value, maximum=160):
    """Return compact display-only metadata without accepting control text."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > maximum:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        return None
    return candidate


def _normalize_language_order(value):
    """Normalize a small ordered language list used as honest metadata."""
    values = value.split(",") if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)):
        return None
    result = []
    for item in values:
        normalized = normalize_locale(item)
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) == 4:
            break
    return result or None


def _system_locale_fallback():
    """Find the process/system locale without manufacturing a foreign locale."""
    candidates = []
    try:
        candidates.append(system_locale.getlocale()[0])
    except (AttributeError, ValueError):
        pass
    try:
        # ``getdefaultlocale`` is deprecated but remains the best fallback on
        # older supported Python builds where the active locale is empty.
        candidates.append(system_locale.getdefaultlocale()[0])
    except (AttributeError, ValueError):
        pass
    for candidate in candidates:
        normalized = normalize_locale(candidate)
        if normalized:
            return normalized
    return "en-US"


def _windows_user_locale():
    """Read the user's Windows locale using an in-process Win32 API call."""
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        buffer = ctypes.create_unicode_buffer(85)
        if kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
            return normalize_locale(buffer.value)
    except (AttributeError, OSError):
        return None
    return None


def _windows_preferred_languages():
    """Read the Windows preferred UI-language order without starting a process."""
    if sys.platform != "win32":
        return []
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_languages = kernel32.GetUserPreferredUILanguages
        get_languages.argtypes = [
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        get_languages.restype = ctypes.c_int
        count = ctypes.c_ulong(0)
        size = ctypes.c_ulong(0)
        # MUI_LANGUAGE_NAME returns BCP-47 names.  The first call asks for the
        # required UTF-16 buffer length; the second fills it in-process.
        if not get_languages(0x00000008, ctypes.byref(count), None, ctypes.byref(size)):
            return []
        buffer = ctypes.create_unicode_buffer(max(1, size.value))
        if not get_languages(0x00000008, ctypes.byref(count), buffer, ctypes.byref(size)):
            return []
        return [
            normalized
            for value in buffer[: size.value].split("\x00")
            if (normalized := normalize_locale(value))
        ]
    except (AttributeError, OSError, TypeError, ValueError):
        return []


def _windows_user_region():
    """Return the Windows user region when the OS exposes one."""
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        buffer = ctypes.create_unicode_buffer(16)
        if kernel32.GetUserDefaultGeoName(buffer, len(buffer)):
            region = buffer.value.strip().upper()
            if re.fullmatch(r"[A-Z]{2,3}", region):
                return region
    except (AttributeError, OSError):
        return None
    return None


def _windows_timezone_key():
    """Read the Windows time-zone key without launching a helper process."""
    if sys.platform != "win32":
        return None
    try:
        class _SystemTime(ctypes.Structure):
            _fields_ = [
                ("wYear", ctypes.c_ushort),
                ("wMonth", ctypes.c_ushort),
                ("wDayOfWeek", ctypes.c_ushort),
                ("wDay", ctypes.c_ushort),
                ("wHour", ctypes.c_ushort),
                ("wMinute", ctypes.c_ushort),
                ("wSecond", ctypes.c_ushort),
                ("wMilliseconds", ctypes.c_ushort),
            ]

        class _DynamicTimeZoneInformation(ctypes.Structure):
            _fields_ = [
                ("Bias", ctypes.c_long),
                ("StandardName", ctypes.c_wchar * 32),
                ("StandardDate", _SystemTime),
                ("StandardBias", ctypes.c_long),
                ("DaylightName", ctypes.c_wchar * 32),
                ("DaylightDate", _SystemTime),
                ("DaylightBias", ctypes.c_long),
                ("TimeZoneKeyName", ctypes.c_wchar * 128),
                ("DynamicDaylightTimeDisabled", ctypes.c_int),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        details = _DynamicTimeZoneInformation()
        result = kernel32.GetDynamicTimeZoneInformation(ctypes.byref(details))
        if result != 0xFFFFFFFF:
            return _safe_metadata_text(details.TimeZoneKeyName or details.StandardName)
    except (AttributeError, OSError):
        return None
    return None


def windows_system_environment():
    """Return locale/time-zone settings from the local operating system.

    This function deliberately has no subprocess or Chromium dependency.  It
    may be injected in tests and is only called at explicit profile creation
    or regeneration, never while merely rendering a profile list.
    """
    locale_name = _windows_user_locale()
    locale_source = "Windows-system-derived" if locale_name else "system-derived fallback"
    if locale_name is None:
        locale_name = _system_locale_fallback()

    timezone_key = _windows_timezone_key()
    timezone_name = WINDOWS_TIMEZONE_TO_IANA.get(timezone_key) if timezone_key else None
    timezone_source = "Windows-system-derived" if timezone_name else "system-derived fallback"
    if timezone_name is None:
        local_zone = datetime.now().astimezone().tzinfo
        candidate = getattr(local_zone, "key", None)
        timezone_name = normalize_timezone(candidate)
        if timezone_name is None and timezone_key:
            # Preserve the real Windows key in metadata rather than pretending
            # that an unknown local zone is UTC.
            timezone_source = "Windows-system-derived (IANA mapping unavailable)"
        elif timezone_name is None:
            # This is only reachable where the platform did not expose a
            # usable zone; UTC is an honest last-resort process fallback.
            timezone_name = "UTC"

    preferred = _windows_preferred_languages()
    language_order = []
    for candidate in [*preferred, locale_name]:
        if candidate not in language_order:
            language_order.append(candidate)
    base_language = locale_name.split("-", 1)[0]
    if base_language not in language_order:
        language_order.append(base_language)
    # These are only last-resort browser-language fallbacks.  They do not
    # replace the actual Windows locale when it is available.
    for fallback in ("en-US", "en"):
        if fallback not in language_order:
            language_order.append(fallback)

    region = _windows_user_region()

    return {
        "locale": locale_name,
        "language_order": language_order,
        "timezone": timezone_name,
        "region": region,
        "windows_timezone_key": timezone_key,
        "locale_source": locale_source,
        "timezone_source": timezone_source,
        "region_source": "Windows-system-derived" if region else "unavailable",
    }


def get_windows_work_area():
    """Return the usable Windows desktop rectangle, excluding the taskbar.

    ``SystemParametersInfoW(SPI_GETWORKAREA)`` is side-effect free and avoids
    hard-coding a monitor size.  A caller can pass a test work area to the
    pure sizing helper below when Win32 is unavailable.
    """
    if sys.platform != "win32":
        return None
    try:
        class _Rect(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long),
            ]

        rect = _Rect()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
            if rect.right > rect.left and rect.bottom > rect.top:
                return {
                    "left": int(rect.left), "top": int(rect.top),
                    "right": int(rect.right), "bottom": int(rect.bottom),
                }
    except (AttributeError, OSError):
        return None
    return None


def _normalize_work_area(value):
    if isinstance(value, dict):
        coordinates = tuple(value.get(name) for name in ("left", "top", "right", "bottom"))
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        coordinates = tuple(value)
    else:
        return None
    if any(isinstance(item, bool) or not isinstance(item, int) for item in coordinates):
        return None
    left, top, right, bottom = coordinates
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def product_window_bounds(profile_id=None, *, work_area=None, slot=None):
    """Calculate one bounded, desktop-usable two-column Chromium rectangle."""
    left, top, right, bottom = (
        _normalize_work_area(work_area)
        or _normalize_work_area(get_windows_work_area())
        or PRODUCT_FALLBACK_WORK_AREA
    )
    total_width = right - left
    total_height = bottom - top
    margin_x = min(PRODUCT_WINDOW_MARGIN, max(8, total_width // 12))
    margin_y = min(PRODUCT_WINDOW_MARGIN, max(8, total_height // 12))
    gap = min(PRODUCT_WINDOW_GAP, max(4, total_width // 24))
    usable_width = max(1, total_width - (2 * margin_x) - gap)
    usable_height = max(1, total_height - (2 * margin_y))
    width = min(usable_width, max(min(PRODUCT_WINDOW_MIN_WIDTH, usable_width), usable_width // 2))
    height = min(usable_height, max(min(PRODUCT_WINDOW_MIN_HEIGHT, usable_height), usable_height))

    if not isinstance(slot, int) or isinstance(slot, bool):
        seed = str(profile_id or "product-profile")
        match = re.search(r"(?:^|[_-])(\d+)$", seed)
        if match:
            slot = (int(match.group(1)) - 1) % 2
        else:
            slot = sha256(seed.encode("utf-8")).digest()[0] % 2
    slot = 0 if slot % 2 == 0 else 1
    requested_left = left + margin_x + (slot * (width + gap))
    maximum_left = max(left, right - margin_x - width)
    x = max(left, min(requested_left, maximum_left))
    y = max(top, min(top + margin_y, max(top, bottom - margin_y - height)))
    return {
        "x": int(x), "y": int(y), "width": int(width), "height": int(height),
        "slot": slot,
        "work_area": {"left": left, "top": top, "right": right, "bottom": bottom},
    }


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


def normalize_user_agent(value):
    """Return a safe explicit User-Agent value or None."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 512 or any(
        ord(char) < 32 or ord(char) == 127 for char in candidate
    ):
        return None
    return candidate


def normalize_window_size_policy(value):
    """Normalize the independent visible-browser-window policy."""
    normalized = _preset_key(value)
    if normalized in ("system", "default", "chromium-default", "chromium"):
        return WINDOW_SIZE_POLICY_SYSTEM
    if normalized in ("desktop", "desktop-friendly", "desktop-default"):
        return WINDOW_SIZE_POLICY_DESKTOP
    if normalized in ("custom", "manual"):
        return WINDOW_SIZE_POLICY_CUSTOM
    return None


def normalize_generation(value):
    """Return a bounded deterministic generation number or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None
    return number if 0 <= number <= 1_000_000 else None


def _normalize_generated_family(value):
    normalized = normalize_environment_preset(value)
    return normalized if normalized in GENERATED_FAMILIES else None


def normalize_environment_config(config):
    """Sanitize runtime fields without allowing argument injection.

    ``viewport_*`` remains the persisted canonical spelling because it is the
    R10 field name. ``window_*`` is accepted as the clearer R11 UI alias.
    """
    if not isinstance(config, dict):
        return None

    def first_value(*names):
        for name in names:
            if name in config:
                return config[name]
        return None

    normalized = {}
    width = normalize_viewport_dimension(
        first_value("window_width", "viewport_width", "width"), 320, 7680
    )
    height = normalize_viewport_dimension(
        first_value("window_height", "viewport_height", "height"), 240, 4320
    )
    language = normalize_locale(first_value("language", "locale"))
    timezone_name = normalize_timezone(first_value("timezone"))
    user_agent = normalize_user_agent(first_value("user_agent", "ua"))
    window_policy = normalize_window_size_policy(
        first_value("window_size_policy", "window_policy")
    )
    generation = normalize_generation(first_value("generated_revision", "generation"))
    generated_family = _normalize_generated_family(first_value("generated_family"))
    if width is not None:
        normalized["viewport_width"] = width
    if height is not None:
        normalized["viewport_height"] = height
    scale = normalize_scale_factor(first_value("device_scale_factor", "scale_factor"))
    if scale is not None:
        normalized["device_scale_factor"] = scale
    if language is not None:
        normalized["language"] = language
    if timezone_name is not None:
        normalized["timezone"] = timezone_name
    if user_agent is not None:
        normalized["user_agent"] = user_agent
    if window_policy is not None:
        normalized["window_size_policy"] = window_policy
    if generation is not None:
        normalized["generated_revision"] = generation
    if generated_family is not None:
        normalized["generated_family"] = generated_family
    for canonical, aliases in {
        "mobile_mode": ("mobile_mode", "mobile"),
        "touch_mode": ("touch_mode", "touch"),
    }.items():
        value = first_value(*aliases)
        if isinstance(value, bool):
            normalized[canonical] = value

    # Product-candidate records carry provenance and a stable non-secret
    # signature.  These values are metadata only; preserving them here means
    # opening/listing an existing profile never regenerates its environment.
    if first_value("environment_schema") == PRODUCT_ENVIRONMENT_SCHEMA:
        normalized["environment_schema"] = PRODUCT_ENVIRONMENT_SCHEMA
        signature = _safe_metadata_text(first_value("environment_signature"), 80)
        if signature and re.fullmatch(r"[a-fA-F0-9-]{8,80}", signature):
            normalized["environment_signature"] = signature.casefold()
        seed = _safe_metadata_text(first_value("environment_seed"), 80)
        if seed and re.fullmatch(r"[a-fA-F0-9-]{8,80}", seed):
            normalized["environment_seed"] = seed.casefold()
        slot = first_value("window_slot")
        if isinstance(slot, str) and slot.strip().isdigit():
            slot = int(slot.strip())
        if isinstance(slot, int) and not isinstance(slot, bool) and 0 <= slot <= 1:
            normalized["window_slot"] = slot
        language_order = _normalize_language_order(first_value("language_order"))
        if language_order:
            normalized["language_order"] = language_order
        region = _safe_metadata_text(first_value("region"), 8)
        if region and re.fullmatch(r"[A-Za-z]{2,3}", region):
            normalized["region"] = region.upper()
        windows_timezone_key = _safe_metadata_text(first_value("windows_timezone_key"), 128)
        if windows_timezone_key:
            normalized["windows_timezone_key"] = windows_timezone_key
        for field in (
            "locale_source", "timezone_source", "region_source",
            "language_source", "user_agent_source", "geometry_source",
            "mobile_source",
        ):
            source = _safe_metadata_text(first_value(field), 160)
            if source:
                normalized[field] = source
    return normalized


def _resolve_window_policy(config, default_policy=None):
    """Apply only an explicit/new policy; leave legacy configs untouched."""
    result = dict(config or {})
    policy = normalize_window_size_policy(result.get("window_size_policy"))
    if policy is None:
        policy = default_policy
    if policy is None:
        return result
    result["window_size_policy"] = policy
    if policy == WINDOW_SIZE_POLICY_SYSTEM:
        result.pop("viewport_width", None)
        result.pop("viewport_height", None)
    elif policy == WINDOW_SIZE_POLICY_DESKTOP:
        result.setdefault("viewport_width", DESKTOP_WINDOW_DEFAULTS["viewport_width"])
        result.setdefault("viewport_height", DESKTOP_WINDOW_DEFAULTS["viewport_height"])
    return result


def product_environment_preset(value):
    """Map the compact product UI labels onto truthful Chromium families."""
    normalized = normalize_environment_preset(value)
    if normalized in (ENVIRONMENT_DESKTOP, ENVIRONMENT_DEFAULT_DESKTOP, ENVIRONMENT_WINDOWS_CHROMIUM):
        return ENVIRONMENT_WINDOWS_CHROMIUM
    if normalized in (ENVIRONMENT_MOBILE, ENVIRONMENT_ANDROID_CHROMIUM):
        return ENVIRONMENT_ANDROID_CHROMIUM
    if normalized == ENVIRONMENT_CUSTOM:
        return ENVIRONMENT_CUSTOM
    if normalized == ENVIRONMENT_GENERATED:
        return ENVIRONMENT_WINDOWS_CHROMIUM
    return ENVIRONMENT_WINDOWS_CHROMIUM


def _product_signature(profile_id, preset, revision, locale_name, timezone_name, seed):
    text = "|".join((
        "discord-profile-manager-product-environment-v1",
        str(profile_id or ""), str(preset), str(revision),
        str(locale_name or ""), str(timezone_name or ""), str(seed),
    ))
    return sha256(text.encode("utf-8")).hexdigest()[:24]


def generate_product_environment(profile_id, preset=ENVIRONMENT_WINDOWS_CHROMIUM, *,
                                 previous_config=None, regenerate=False,
                                 system_settings=None):
    """Generate a persisted, coherent product environment without launching Chromium.

    The only intentionally variable values are safe metadata/runtime requests
    that this Windows Chromium deployment can represent honestly.  The Chrome
    version is always the bundled runtime version; signatures are distinct by
    profile seed rather than fabricated browser versions or hardware values.
    """
    current = normalize_environment_config(previous_config) or {}
    prior_revision = normalize_generation(current.get("generated_revision"))
    revision = (prior_revision + 1) if regenerate and prior_revision is not None else 0
    requested = normalize_environment_preset(preset)
    if requested == ENVIRONMENT_GENERATED:
        # Generated identities can vary only between runtime-supported Windows
        # and mobile identity requests.  They never invent a different
        # Chromium version or hardware identity.
        family_digest = sha256(
            f"discord-profile-manager-generated-family:{profile_id}:{revision}".encode("utf-8")
        ).digest()
        target = (
            ENVIRONMENT_ANDROID_CHROMIUM
            if family_digest[0] % 2
            else ENVIRONMENT_WINDOWS_CHROMIUM
        )
        previous_family = _normalize_generated_family(current.get("generated_family"))
        if regenerate and previous_family == target:
            target = (
                ENVIRONMENT_WINDOWS_CHROMIUM
                if target == ENVIRONMENT_ANDROID_CHROMIUM
                else ENVIRONMENT_ANDROID_CHROMIUM
            )
    else:
        target = product_environment_preset(requested)
    settings = dict(system_settings or windows_system_environment())
    locale_name = normalize_locale(settings.get("locale")) or _system_locale_fallback()
    timezone_name = normalize_timezone(settings.get("timezone"))
    region = _safe_metadata_text(settings.get("region"), 8)
    if region and re.fullmatch(r"[A-Za-z]{2,3}", region):
        region = region.upper()
    else:
        region = None
    language_order = _normalize_language_order(settings.get("language_order")) or [locale_name]
    if locale_name not in language_order:
        language_order.insert(0, locale_name)
    for fallback in (locale_name.split("-", 1)[0], "en-US", "en"):
        if fallback not in language_order:
            language_order.append(fallback)
    language_order = language_order[:4]

    seed_material = "|".join((
        "discord-profile-manager-product-seed-v1", str(profile_id or ""),
        str(target), str(revision), locale_name, str(timezone_name or ""),
        str(region or ""),
    ))
    seed = sha256(seed_material.encode("utf-8")).hexdigest()[:24]
    mobile = target == ENVIRONMENT_ANDROID_CHROMIUM
    result = {
        "environment_schema": PRODUCT_ENVIRONMENT_SCHEMA,
        "generated_family": target,
        "generated_revision": revision,
        "environment_seed": seed,
        "environment_signature": _product_signature(
            profile_id, target, revision, locale_name, timezone_name, seed
        ),
        "window_slot": int(seed[-1], 16) % 2,
        "user_agent": user_agent_for_family(target, CHROMIUM_VERSION),
        "language": locale_name,
        "language_order": language_order,
        "mobile_mode": mobile,
        "touch_mode": mobile,
        "locale_source": settings.get("locale_source") or "Windows-system-derived",
        "language_source": "Windows-system-derived; applied to Chromium",
        "user_agent_source": "generated; applied to Chromium",
        "geometry_source": "generated; applied to Chromium",
        "mobile_source": (
            "generated; User-Agent and touch request applied; full mobile emulation unsupported"
            if mobile else "generated; desktop identity applied to Chromium"
        ),
        "timezone_source": settings.get("timezone_source") or "Windows-system-derived",
        "region_source": settings.get("region_source") or "Windows-system-derived",
    }
    if timezone_name:
        result["timezone"] = timezone_name
    if region:
        result["region"] = region
    windows_timezone_key = _safe_metadata_text(settings.get("windows_timezone_key"), 128)
    if windows_timezone_key:
        result["windows_timezone_key"] = windows_timezone_key
    return result


def product_custom_environment(
    profile_id, custom_config=None, *, previous_config=None, system_settings=None
):
    """Persist a user-edited Custom environment without silently regenerating it."""
    current = normalize_environment_config(previous_config) or {}
    supplied = normalize_environment_config(custom_config) or {}
    base = dict(current) if current.get("environment_schema") == PRODUCT_ENVIRONMENT_SCHEMA else {}
    target = ENVIRONMENT_CUSTOM
    for key in (
        "user_agent", "language", "timezone", "mobile_mode", "touch_mode",
        "language_order", "region", "window_slot",
    ):
        if key in supplied:
            base[key] = supplied[key]
    if not base.get("user_agent"):
        base["user_agent"] = user_agent_for_family(ENVIRONMENT_WINDOWS_CHROMIUM, CHROMIUM_VERSION)
    if not base.get("language"):
        settings = dict(system_settings or windows_system_environment())
        base["language"] = normalize_locale(settings.get("locale")) or _system_locale_fallback()
        base["language_order"] = _normalize_language_order(settings.get("language_order")) or [base["language"]]
        if settings.get("timezone"):
            base["timezone"] = normalize_timezone(settings["timezone"])
        if settings.get("region"):
            base["region"] = str(settings["region"]).upper()
        if settings.get("windows_timezone_key"):
            base["windows_timezone_key"] = settings["windows_timezone_key"]
    base["environment_schema"] = PRODUCT_ENVIRONMENT_SCHEMA
    base["generated_family"] = ENVIRONMENT_WINDOWS_CHROMIUM
    base["generated_revision"] = normalize_generation(base.get("generated_revision")) or 0
    seed = base.get("environment_seed") or sha256(
        f"discord-profile-manager-product-custom|{profile_id}".encode("utf-8")
    ).hexdigest()[:24]
    base["environment_seed"] = seed
    base["window_slot"] = int(base.get("window_slot", int(seed[-1], 16) % 2)) % 2
    base["environment_signature"] = _product_signature(
        profile_id, target, base["generated_revision"], base.get("language"),
        base.get("timezone"), seed,
    )
    base["locale_source"] = "user-edited" if supplied.get("language") else "Windows-system-derived"
    base["language_source"] = "user-edited; applied to Chromium"
    base["user_agent_source"] = "user-edited; applied to Chromium"
    base["geometry_source"] = "generated; applied to Chromium"
    base["timezone_source"] = "user-edited; metadata-only" if supplied.get("timezone") else "Windows-system-derived; metadata-only"
    base["mobile_source"] = "user-edited; full mobile emulation unsupported"
    base.pop("device_scale_factor", None)
    base.pop("viewport_width", None)
    base.pop("viewport_height", None)
    return base


def deterministic_generated_environment(profile_id, generation=0, previous_family=None):
    """Build one deterministic, internally consistent generated identity.

    The caller persists this result. No launch path calls this function, so a
    generated profile cannot silently change identity between launches.
    """
    safe_profile_id = "" if profile_id is None else str(profile_id)
    safe_generation = normalize_generation(generation)
    if safe_generation is None:
        safe_generation = 0
    digest = sha256(
        f"discord-profile-manager-r11:{safe_profile_id}:{safe_generation}".encode("utf-8")
    ).digest()
    family = GENERATED_FAMILIES[digest[0] % len(GENERATED_FAMILIES)]
    previous = _normalize_generated_family(previous_family)
    if previous is not None and family == previous:
        family = GENERATED_FAMILIES[
            (GENERATED_FAMILIES.index(family) + 1) % len(GENERATED_FAMILIES)
        ]
    result = dict(PRESET_ENVIRONMENT_DEFAULTS[family])
    result.update({
        "generated_family": family,
        "generated_revision": safe_generation,
    })
    result["timezone"] = {
        ENVIRONMENT_WINDOWS_CHROMIUM: "America/New_York",
        ENVIRONMENT_LINUX_CHROMIUM: "Europe/London",
        ENVIRONMENT_ANDROID_CHROMIUM: "America/Los_Angeles",
    }[family]
    return result


# Friendly alias for callers that do not need to care about the implementation
# term "deterministic".
generate_environment = deterministic_generated_environment


def materialize_environment_config(
    profile_id, preset, config=None, *, existing_config=None, regenerate=False
):
    """Return the exact configuration that should be persisted for a preset.

    Fixed identities may vary their visible window policy and timezone
    metadata, but their UA/DPR/touch fields remain a compatible family. A
    generated identity is created once here and preserved until explicit
    regeneration.
    """
    normalized_preset = normalize_environment_preset(preset)
    normalized_config = normalize_environment_config(config) or {}
    existing = normalize_environment_config(existing_config) or {}

    # Product-candidate configuration is intentionally self-contained.  Do
    # not hydrate it with the legacy viewport/DPR defaults: product launch
    # geometry is calculated from the current Windows work area instead.
    if normalized_config.get("environment_schema") == PRODUCT_ENVIRONMENT_SCHEMA:
        result = dict(normalized_config)
        result.pop("device_scale_factor", None)
        result.pop("viewport_width", None)
        result.pop("viewport_height", None)
        result.pop("window_size_policy", None)
        return result

    if normalized_preset in (ENVIRONMENT_DESKTOP, ENVIRONMENT_DEFAULT_DESKTOP):
        return None
    if normalized_preset == ENVIRONMENT_MOBILE:
        # Exact R10 save semantics for pre-existing records only.
        keys = (
            "viewport_width", "viewport_height", "device_scale_factor",
            "language", "timezone",
        )
        result = {key: normalized_config[key] for key in keys if key in normalized_config}
        return result or None
    if normalized_preset == ENVIRONMENT_CUSTOM:
        return _resolve_window_policy(normalized_config) if normalized_config else {}
    if normalized_preset == ENVIRONMENT_GENERATED:
        prior_family = existing.get("generated_family")
        if existing and prior_family in GENERATED_FAMILIES and not regenerate:
            return _resolve_window_policy(existing, WINDOW_SIZE_POLICY_DESKTOP)
        prior_generation = normalize_generation(existing.get("generated_revision"))
        generation = (
            prior_generation + 1
            if regenerate and prior_generation is not None
            else 0
        )
        return deterministic_generated_environment(
            profile_id, generation, prior_family if regenerate else None
        )

    # New fixed identities always retain a coherent UA, DPR, and touch family.
    result = dict(PRESET_ENVIRONMENT_DEFAULTS[normalized_preset])
    for key in ("window_size_policy", "viewport_width", "viewport_height", "timezone"):
        if key in normalized_config:
            result[key] = normalized_config[key]
        elif key in existing:
            result[key] = existing[key]
    return _resolve_window_policy(result, WINDOW_SIZE_POLICY_DESKTOP)


def effective_environment(record):
    """Return a normalized, non-mutating environment for one metadata record."""
    record = record if isinstance(record, dict) else {}
    preset = normalize_environment_preset(record.get("environment_preset"))
    raw_config = record.get("environment_config")
    product_config = normalize_environment_config(raw_config)
    if product_config and product_config.get("environment_schema") == PRODUCT_ENVIRONMENT_SCHEMA:
        # Product environments are persisted independently of the compact
        # Desktop/Mobile label.  Do not let the legacy Desktop fast-path hide
        # their generated values on list, edit, or export.
        return preset, product_config
    if preset in (ENVIRONMENT_DESKTOP, ENVIRONMENT_DEFAULT_DESKTOP):
        return preset, {}
    if preset == ENVIRONMENT_MOBILE:
        # Do not alter existing saved legacy Mobile profile behaviour. The
        # visible R11 preset is android_chromium instead.
        config = dict(MOBILE_ENVIRONMENT_DEFAULTS)
        custom = normalize_environment_config(raw_config)
        if custom:
            for key in (
                "viewport_width", "viewport_height", "device_scale_factor", "language"
            ):
                if key in custom:
                    config[key] = custom[key]
            if "timezone" in custom:
                config["timezone"] = custom["timezone"]
        config["mobile_mode"] = True
        config["touch_mode"] = True
        return preset, config
    if preset == ENVIRONMENT_CUSTOM:
        config = normalize_environment_config(raw_config)
        if not config:
            return ENVIRONMENT_DESKTOP, {}
        return preset, _resolve_window_policy(config)
    if preset == ENVIRONMENT_GENERATED:
        config = normalize_environment_config(raw_config)
        family = config.get("generated_family") if config else None
        if family not in GENERATED_FAMILIES:
            # A malformed manually-edited record gets a stable, safe fallback.
            config = deterministic_generated_environment("legacy-generated", 0)
        return preset, _resolve_window_policy(config, WINDOW_SIZE_POLICY_DESKTOP)

    defaults = dict(PRESET_ENVIRONMENT_DEFAULTS[preset])
    custom = normalize_environment_config(raw_config)
    if custom:
        # Fixed presets permit an independent visible-window policy and stored
        # timezone; they do not accept a mismatched UA or mobile/DPR tuple.
        for key in ("window_size_policy", "viewport_width", "viewport_height", "timezone"):
            if key in custom:
                defaults[key] = custom[key]
    return preset, _resolve_window_policy(defaults, WINDOW_SIZE_POLICY_DESKTOP)


def environment_editor_state(preset, custom_config=None):
    """Return display values and editability for the legacy/R11 editors."""
    normalized_preset = normalize_environment_preset(preset)
    if normalized_preset in (ENVIRONMENT_DESKTOP, ENVIRONMENT_DEFAULT_DESKTOP):
        return {
            "preset": normalized_preset,
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
    if normalized_preset == ENVIRONMENT_CUSTOM:
        config = normalize_environment_config(custom_config) or {}
        result = {
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
        # Preserve the exact legacy editor-state mapping when it is called by
        # old consumers. R11-specific fields opt into the richer state.
        if "user_agent" in config or "window_size_policy" in config:
            result.update({
                "user_agent": config.get("user_agent", ""),
                "window_size_policy": config.get(
                    "window_size_policy", WINDOW_SIZE_POLICY_SYSTEM
                ),
                "identity_editable": True,
                "window_editable": True,
            })
        return result

    _, config = effective_environment({
        "environment_preset": normalized_preset,
        "environment_config": custom_config,
    })
    return {
        "preset": normalized_preset,
        **dict(config),
        "editable": False,
        "identity_editable": False,
        "window_editable": True,
    }


def runtime_environment_editor_state(record):
    """Return the R11 editor state for a persisted record.

    A legacy ``mobile`` record is shown as Android Chromium for its next
    intentional save, while it keeps legacy launch behaviour until then.
    """
    record = record if isinstance(record, dict) else {}
    preset, config = effective_environment(record)
    if preset == ENVIRONMENT_MOBILE:
        converted = {
            "window_size_policy": WINDOW_SIZE_POLICY_CUSTOM,
            "viewport_width": config.get("viewport_width"),
            "viewport_height": config.get("viewport_height"),
            "timezone": config.get("timezone", ""),
        }
        state = environment_editor_state(ENVIRONMENT_ANDROID_CHROMIUM, converted)
        state["legacy_mobile_record"] = True
        return state
    state = environment_editor_state(preset, config)
    state.setdefault("user_agent", config.get("user_agent", ""))
    state.setdefault(
        "window_size_policy",
        config.get("window_size_policy", WINDOW_SIZE_POLICY_SYSTEM),
    )
    state.setdefault("identity_editable", preset == ENVIRONMENT_CUSTOM)
    state.setdefault(
        "window_editable",
        preset not in (ENVIRONMENT_DESKTOP, ENVIRONMENT_DEFAULT_DESKTOP),
    )
    return state


def environment_launch_arguments(record):
    """Build safe Chromium launch switches for one profile environment."""
    preset, config = effective_environment(record)
    arguments = []
    width = config.get("viewport_width")
    height = config.get("viewport_height")
    if width is not None and height is not None:
        arguments.append(f"--window-size={width},{height}")
    if "device_scale_factor" in config:
        arguments.append(f"--force-device-scale-factor={config['device_scale_factor']:g}")
    if config.get("language"):
        arguments.append(f"--lang={config['language']}")
    if config.get("user_agent"):
        arguments.append(f"--user-agent={config['user_agent']}")
    # R11 Android Chromium uses the explicit UA above. This legacy switch is
    # retained only for saved R10 mobile records because Windows Chromium does
    # not reliably change UA from --use-mobile-user-agent.
    legacy_custom_mobile = (
        preset == ENVIRONMENT_CUSTOM
        and config.get("mobile_mode")
        and "user_agent" not in config
        and "window_size_policy" not in config
    )
    if (preset == ENVIRONMENT_MOBILE or legacy_custom_mobile) and config.get("mobile_mode"):
        arguments.append("--use-mobile-user-agent")
    if "touch_mode" in config:
        arguments.append(
            "--touch-events=enabled" if config["touch_mode"] else "--touch-events=disabled"
        )
    return arguments


def product_environment_details(record, *, work_area=None):
    """Return the product-only environment view without legacy DPR coupling."""
    record = record if isinstance(record, dict) else {}
    preset = normalize_environment_preset(record.get("environment_preset"))
    raw = normalize_environment_config(record.get("environment_config")) or {}
    if raw.get("environment_schema") == PRODUCT_ENVIRONMENT_SCHEMA:
        config = dict(raw)
    else:
        _, config = effective_environment(record)
        config = dict(config)
    config.pop("device_scale_factor", None)
    config.pop("viewport_width", None)
    config.pop("viewport_height", None)
    config.pop("window_size_policy", None)
    bounds = product_window_bounds(
        record.get("profile_id"), work_area=work_area, slot=config.get("window_slot")
    )
    field_sources = {
        "user_agent": config.get("user_agent_source") or "applied to Chromium",
        "language": config.get("language_source") or "applied to Chromium",
        "language_order": "Windows-system-derived; metadata-only preference order",
        "timezone": (
            f"{config.get('timezone_source')}; metadata-only"
            if config.get("timezone_source") else "metadata-only"
        ),
        "region": config.get("region_source") or "metadata-only",
        "window_geometry": config.get("geometry_source") or "generated; applied to Chromium",
        "mobile": config.get("mobile_source") or "unsupported full mobile emulation",
        "runtime_version": "read-only bundled runtime",
        "signature": "generated duplicate-detection metadata",
    }
    return {
        "preset": preset,
        "generated_family": config.get("generated_family"),
        "generated_revision": config.get("generated_revision"),
        "environment_seed": config.get("environment_seed"),
        "user_agent": config.get("user_agent"),
        "language": config.get("language"),
        "language_order": list(config.get("language_order") or ()),
        "timezone": config.get("timezone"),
        "region": config.get("region"),
        "windows_timezone_key": config.get("windows_timezone_key"),
        "mobile_mode": bool(config.get("mobile_mode", False)),
        "touch_mode": bool(config.get("touch_mode", False)),
        "generated": raw.get("environment_schema") == PRODUCT_ENVIRONMENT_SCHEMA,
        "signature": config.get("environment_signature"),
        "window_slot": bounds["slot"],
        "window_geometry": bounds,
        "field_sources": field_sources,
        "runtime_version": CHROMIUM_VERSION,
        "timezone_applied": False,
        "unsupported_mobile_emulation": bool(config.get("mobile_mode", False)),
    }


def product_environment_launch_arguments(record):
    """Build product Chromium arguments with work-area bounds and normal DPR.

    This is intentionally separate from ``environment_launch_arguments`` to
    preserve the frozen legacy/refactor compatibility path.  It reads old DPR
    values safely but never forwards them to Chromium.
    """
    details = product_environment_details(record)
    bounds = details["window_geometry"]
    arguments = [
        f"--window-size={bounds['width']},{bounds['height']}",
        f"--window-position={bounds['x']},{bounds['y']}",
    ]
    language = normalize_locale(details.get("language"))
    if language:
        arguments.append(f"--lang={language}")
    user_agent = normalize_user_agent(details.get("user_agent"))
    if user_agent:
        arguments.append(f"--user-agent={user_agent}")
    if details.get("touch_mode"):
        arguments.append("--touch-events=enabled")
    elif details.get("touch_mode") is False and details.get("preset") != ENVIRONMENT_DESKTOP:
        arguments.append("--touch-events=disabled")
    return arguments


def product_environment_runtime_notes(record):
    """State product limitations without claiming unsupported spoofing."""
    details = product_environment_details(record)
    notes = [
        "Chromium window bounds are calculated from the current Windows work area.",
        "Device scale is left to normal Windows/Chromium desktop scaling.",
    ]
    if details.get("language"):
        notes.append("Language is requested through Chromium --lang; website preference behavior remains Chromium-controlled.")
    if details.get("timezone"):
        notes.append("Timezone is persisted as metadata only; this build does not override Chromium/Windows timezone behavior.")
    if details.get("mobile_mode"):
        notes.append("Mobile requests use a coherent Android Chromium User-Agent and touch events; full device emulation is unsupported.")
    return notes


def chromium_file_version(browser_path):
    """Read a Windows executable's version resource without executing it."""
    path = Path(browser_path)
    if not path.is_file() or sys.platform != "win32":
        return None
    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        ignored = ctypes.c_uint(0)
        size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, data):
            return None
        value = ctypes.c_void_p()
        length = ctypes.c_uint(0)
        if not version.VerQueryValueW(data, "\\", ctypes.byref(value), ctypes.byref(length)):
            return None

        class _FixedFileInfo(ctypes.Structure):
            _fields_ = [
                ("dwSignature", ctypes.c_uint32),
                ("dwStrucVersion", ctypes.c_uint32),
                ("dwFileVersionMS", ctypes.c_uint32),
                ("dwFileVersionLS", ctypes.c_uint32),
                ("dwProductVersionMS", ctypes.c_uint32),
                ("dwProductVersionLS", ctypes.c_uint32),
                ("dwFileFlagsMask", ctypes.c_uint32),
                ("dwFileFlags", ctypes.c_uint32),
                ("dwFileOS", ctypes.c_uint32),
                ("dwFileType", ctypes.c_uint32),
                ("dwFileSubtype", ctypes.c_uint32),
                ("dwFileDateMS", ctypes.c_uint32),
                ("dwFileDateLS", ctypes.c_uint32),
            ]

        fixed = ctypes.cast(value, ctypes.POINTER(_FixedFileInfo)).contents
        if fixed.dwSignature != 0xFEEF04BD:
            return None
        version_text = ".".join(str(part) for part in (
            (fixed.dwFileVersionMS >> 16) & 0xFFFF,
            fixed.dwFileVersionMS & 0xFFFF,
            (fixed.dwFileVersionLS >> 16) & 0xFFFF,
            fixed.dwFileVersionLS & 0xFFFF,
        ))
        return version_text if re.fullmatch(r"\d+(?:\.\d+){3}", version_text) else None
    except (AttributeError, OSError, ValueError):
        return None


ENVIRONMENT_RUNTIME_GUIDANCE = (
    "Set both window dimensions to request browser window bounds, not an exact page viewport. "
    "Language requests the browser UI locale, not website language preferences. "
    "Timezone overrides and legacy mobile device emulation are unsupported on Windows. "
    "Touch mode requests touch event support, not mobile device emulation. "
    "Close and reopen Chromium to apply supported changes."
)
RUNTIME_SETTINGS_GUIDANCE = (
    "Browser window size and environment identity are independent. "
    "Timezone is saved as metadata only and is not applied to Chromium at launch. "
    "User-Agent, language, DPR, touch, window size, and proxy changes apply after closing and reopening Chromium."
)


def environment_runtime_notes(record):
    """Identify retained settings whose runtime meaning is limited."""
    preset, config = effective_environment(record)
    notes = []
    if "viewport_width" in config or "viewport_height" in config:
        if "viewport_width" not in config or "viewport_height" not in config:
            notes.append("Both window width and height are required; no window-size switch is generated.")
        else:
            notes.append("Window dimensions request browser window bounds, not an exact page viewport; Chromium may enforce a minimum size.")
    if config.get("language"):
        notes.append("Language requests the browser UI locale; website language preferences are not changed.")
    if config.get("user_agent"):
        notes.append("User-Agent is explicitly passed to Chromium for this launch.")
    if config.get("timezone"):
        notes.append("Timezone is saved only; the Chromium launch path does not apply a timezone override.")
    if preset == ENVIRONMENT_MOBILE and config.get("mobile_mode"):
        notes.append("Mobile device emulation is unsupported on Windows; Chromium ignores the retained --use-mobile-user-agent switch.")
    if preset == ENVIRONMENT_ANDROID_CHROMIUM:
        notes.append("Android Chromium identity uses an explicit Chromium-compatible Android User-Agent; it does not use the unreliable mobile-UA switch.")
    if "touch_mode" in config:
        notes.append("Touch mode requests touch event support; it does not emulate a mobile device or guarantee touch hardware.")
    return notes
