"""Safe, deterministic Chromium runtime-environment policy.

The original ``mobile`` preset is deliberately retained as a legacy-record
compatibility path. New Runtime Settings use the Chromium-specific presets
below instead. In particular, Android identity and browser-window geometry
are independent: Android does not inherit the legacy phone-sized window.
"""

from hashlib import sha256
from math import isfinite
import re
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

_CHROMIUM_VERSION = "131.0.0.0"
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
    scale = normalize_scale_factor(first_value("device_scale_factor", "scale_factor"))
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
