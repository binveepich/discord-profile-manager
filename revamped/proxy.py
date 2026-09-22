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


def _normalize_proxy_credential(value, field):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 320:
        raise ProxyValidationError(f"Proxy {field} must be non-empty text.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ProxyValidationError(f"Proxy {field} contains invalid characters.")
    return value


def normalize_proxy_credentials(username=None, password=None):
    """Validate optional credentials for explicit user-owned export/storage."""
    if username is None and password is None:
        return {"username": None, "password": None}
    username = _normalize_proxy_credential(username, "username")
    password = _normalize_proxy_credential(password, "password")
    if (username is None) != (password is None):
        raise ProxyValidationError(
            "Proxy username and password must be provided together."
        )
    return {"username": username, "password": password}


def normalize_proxy_config(scheme, host, port):
    """Normalize a complete enabled proxy or return None when malformed."""
    normalized = {
        "scheme": normalize_proxy_scheme(scheme),
        "host": normalize_proxy_host(host),
        "port": normalize_proxy_port(port),
    }
    return normalized if all(value is not None for value in normalized.values()) else None


def effective_proxy(record):
    """Return one record's safe proxy state without mutating metadata."""
    if not isinstance(record, dict) or record.get("proxy_enabled") is not True:
        return _proxy_off_state()
    normalized = normalize_proxy_config(
        record.get("proxy_scheme"), record.get("proxy_host"), record.get("proxy_port")
    )
    if normalized is None:
        return _proxy_off_state()
    result = {"enabled": True, **normalized}
    for field in ("username", "password"):
        value = record.get(f"proxy_{field}")
        if isinstance(value, str) and value:
            result[field] = value
    return result


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
    """Parse common endpoint forms; any credentials remain transient only."""
    if not isinstance(value, str) or not value.strip():
        raise ProxyValidationError("Proxy string is empty.")
    text = value.strip()
    username = None
    password = None
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
            userinfo, endpoint = authority.split("@", 1)
            if "@" in endpoint or ":" not in userinfo:
                raise ProxyValidationError("Authenticated proxy syntax is malformed.")
            username, password = userinfo.split(":", 1)
            if not username or not password:
                raise ProxyValidationError("Authenticated proxy syntax requires username and password.")
            if endpoint.count(":") > 1 and not endpoint.startswith("["):
                raise ProxyValidationError("Authenticated IPv6 proxies must use [host]:port syntax.")
        host, port = _parse_proxy_host_port(
            endpoint if "@" in authority else authority,
            allow_raw_ipv6=username is None,
        )
    else:
        if text.startswith("["):
            closing = text.find("]")
            if closing < 0 or not text[closing + 1:].startswith(":"):
                raise ProxyValidationError("IPv6 proxy hosts must use [host]:port syntax.")
            host_value = text[:closing + 1]
            suffix = text[closing + 2:]
            fields = suffix.split(":", 2)
            if len(fields) == 1:
                port_value = fields[0]
            elif len(fields) == 3:
                port_value, username, password = fields
                if not username or not password:
                    raise ProxyValidationError("Authenticated proxy syntax requires username and password.")
            else:
                raise ProxyValidationError("Authenticated proxy syntax is malformed.")
            host, port = _parse_proxy_host_port(
                f"{host_value}:{port_value}", allow_raw_ipv6=False
            )
        elif text.count(":") > 1:
            try:
                host, port = _parse_proxy_host_port(text, allow_raw_ipv6=True)
            except ProxyValidationError:
                fields = text.split(":", 3)
                if len(fields) != 4:
                    raise
                host, port = _parse_proxy_host_port(
                    f"{fields[0]}:{fields[1]}", allow_raw_ipv6=False
                )
                username, password = fields[2], fields[3]
                if not username or not password:
                    raise ProxyValidationError("Authenticated proxy syntax requires username and password.")
        else:
            fields = text.split(":", 3)
            if len(fields) == 2:
                host, port = _parse_proxy_host_port(text, allow_raw_ipv6=False)
            elif len(fields) == 4:
                host, port = _parse_proxy_host_port(
                    f"{fields[0]}:{fields[1]}", allow_raw_ipv6=False
                )
                username, password = fields[2], fields[3]
                if not username or not password:
                    raise ProxyValidationError("Authenticated proxy syntax requires username and password.")
            else:
                raise ProxyValidationError("Proxy string must use host:port syntax.")
    return {
        "scheme": scheme,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "authenticated": username is not None or password is not None,
    }
