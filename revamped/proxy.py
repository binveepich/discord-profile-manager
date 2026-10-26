"""Offline, unauthenticated M8 proxy policy."""

import ipaddress
import re

from .core import ProxyValidationError


SUPPORTED_PROXY_SCHEMES = ("http", "https", "socks4", "socks5")
PROXY_HOST_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
PROXY_HOST_PATTERN = re.compile(r"^[A-Za-z0-9.-]+$")


def normalize_proxy_scheme(value):
    """Return one of the supported Chromium proxy schemes."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().casefold()
    return candidate if candidate in SUPPORTED_PROXY_SCHEMES else None


def normalize_proxy_host(value):
    """Return a hostname/IP literal without scheme, port, or credentials."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 253:
        return None
    if any(ord(char) < 32 or char.isspace() for char in candidate):
        return None
    if candidate.startswith("[") or candidate.endswith("]"):
        if not (candidate.startswith("[") and candidate.endswith("]")):
            return None
        candidate = candidate[1:-1]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        address = None
    if address is not None:
        return address.compressed.casefold()
    if ":" in candidate or not PROXY_HOST_PATTERN.fullmatch(candidate):
        return None
    labels = candidate.rstrip(".").split(".")
    if not labels or any(not PROXY_HOST_LABEL_PATTERN.fullmatch(label) for label in labels):
        return None
    return ".".join(labels).casefold()


def normalize_proxy_port(value):
    """Return a TCP port in the valid 1–65535 range, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        port = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        try:
            port = int(value.strip())
        except ValueError:
            return None
    else:
        return None
    return port if 1 <= port <= 65535 else None


def _proxy_off_state():
    return {
        "enabled": False,
        "scheme": None,
        "host": None,
        "port": None,
    }


def normalize_proxy_config(scheme, host, port):
    """Normalize a complete enabled proxy or return None when malformed."""
    normalized = {
        "scheme": normalize_proxy_scheme(scheme),
        "host": normalize_proxy_host(host),
        "port": normalize_proxy_port(port),
    }
    return normalized if all(value is not None for value in normalized.values()) else None


def effective_proxy(record):
    """Return one record's endpoint-only proxy state without mutation."""
    if not isinstance(record, dict) or record.get("proxy_enabled") is not True:
        return _proxy_off_state()
    normalized = normalize_proxy_config(
        record.get("proxy_scheme"), record.get("proxy_host"), record.get("proxy_port")
    )
    if normalized is None:
        return _proxy_off_state()
    return {"enabled": True, **normalized}


def proxy_launch_arguments(record):
    """Build one proxy switch, or none when inactive/malformed."""
    proxy = effective_proxy(record)
    if not proxy["enabled"]:
        return []
    host = proxy["host"]
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    return [f"--proxy-server={proxy['scheme']}://{host}:{proxy['port']}"]


def _parse_proxy_host_port(value, allow_raw_ipv6=True):
    """Parse a host/port endpoint without guessing through malformed colons."""
    candidate = value.strip()
    if not candidate:
        raise ProxyValidationError("Proxy string must include a host and port.")
    if candidate.startswith("["):
        closing = candidate.find("]")
        if closing < 0 or not candidate[closing + 1:].startswith(":"):
            raise ProxyValidationError("IPv6 proxy hosts must use [host]:port syntax.")
        host_value = candidate[:closing + 1]
        port_value = candidate[closing + 2:]
        if ":" in port_value:
            raise ProxyValidationError("Proxy string contains an ambiguous host or port.")
    elif candidate.count(":") == 1:
        host_value, port_value = candidate.rsplit(":", 1)
    elif allow_raw_ipv6 and candidate.count(":") > 1:
        possible_host, possible_port = candidate.rsplit(":", 1)
        if ":" not in possible_host:
            raise ProxyValidationError("Proxy string contains an ambiguous host or port.")
        host_value, port_value = possible_host, possible_port
    else:
        raise ProxyValidationError("Proxy string must use host:port syntax.")
    host = normalize_proxy_host(host_value)
    if host is None:
        raise ProxyValidationError(
            "Proxy host must be a hostname or IP address without credentials or a path."
        )
    port = normalize_proxy_port(port_value)
    if port is None:
        raise ProxyValidationError("Proxy port must be a number from 1 to 65535.")
    return host, port


def parse_proxy_string(value):
    """Parse an unauthenticated proxy endpoint without retaining auth input."""
    if not isinstance(value, str) or not value.strip():
        raise ProxyValidationError("Proxy string is empty.")
    text = value.strip()
    scheme = "http"

    if "://" in text:
        scheme_value, authority = text.split("://", 1)
        scheme = normalize_proxy_scheme(scheme_value)
        if scheme is None:
            raise ProxyValidationError(
                "Unsupported proxy scheme. Choose HTTP, HTTPS, SOCKS4, or SOCKS5."
            )
        if not authority or any(char in authority for char in "/?#"):
            raise ProxyValidationError("Proxy string contains an invalid authority.")
        if "@" in authority:
            raise ProxyValidationError("Proxy endpoints must not include authentication data.")
        host, port = _parse_proxy_host_port(authority)
    else:
        if "@" in text:
            raise ProxyValidationError("Proxy endpoints must not include authentication data.")
        if text.count(":") > 1 and not text.startswith("["):
            try:
                host, port = _parse_proxy_host_port(text, allow_raw_ipv6=True)
            except ProxyValidationError as error:
                raise ProxyValidationError(
                    "Proxy input must be an unauthenticated host:port endpoint."
                ) from error
        else:
            host, port = _parse_proxy_host_port(text, allow_raw_ipv6=False)

    return {"scheme": scheme, "host": host, "port": port}
