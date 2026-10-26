"""Python-authoritative product API exposed to the React/pywebview shell.

The API deliberately exposes operations instead of filesystem or process
primitives.  All values crossing the bridge are JSON-safe DTOs and account
secrets are only accepted as transient input to the explicit legacy-compatible
Autofill workflow.
"""

import csv
from datetime import datetime
import io
import json
import logging
import re
import subprocess
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import (
    ProxyHandler,
    Request,
    build_opener,
    urlopen,
)

from . import environment, proxy
from .accounts import derive_profile_name, parse_account_input
from .core import ProfileManagerError
from .profiles import MAX_DISPLAYED_PROFILES, table_order


_SECRET_WORDS = (
    "password", "totp", "secret", "token", "cookie", "session",
    "credential", "authorization",
)

CONTRIBUTOR_NAME = "merino sầu riêng"

# Task names the loading splash may report. Other names are ignored, so the bridge cannot write arbitrary log lines.
STARTUP_TASK_IDS = frozenset(("bridge", "catalog", "profiles", "preferences", "runtime", "about"))
_LOGGER = logging.getLogger("discord-profile-manager.product")


EXPORT_COLUMNS = (
    "profile_id",
    "stt",
    "display_name",
    "email",
    "password",
    "totp_secret",
    "has_2fa",
    "discord_token",
    "account_mode",
    "account_label",
    "environment_mode",
    "environment_locale",
    "environment_language_order",
    "environment_timezone",
    "environment_region",
    "environment_user_agent",
    "environment_mobile",
    "environment_touch",
    "environment_signature",
    "proxy_enabled",
    "proxy_scheme",
    "proxy_host",
    "proxy_port",
    "created_at",
    "updated_at",
    "last_used",
    "status",
)


def _looks_sensitive(name):
    normalized = str(name).casefold().replace("_", "").replace("-", "")
    return any(word in normalized for word in _SECRET_WORDS)


def _json_safe(value, *, drop_sensitive=True):
    """Return a conservative JSON-safe copy of arbitrary service output."""
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item, drop_sensitive=drop_sensitive)
            for key, item in value.items()
            if not (drop_sensitive and _looks_sensitive(key))
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, drop_sensitive=drop_sensitive) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class JobManager:
    """Small thread-backed job registry for bridge-safe long operations."""

    MAX_RETAINED_JOBS = 256

    def __init__(self, max_workers=2):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.RLock()
        self._jobs = {}
        self._shutdown = False
        self._shutdown_complete = threading.Event()

    def start(self, label, worker, initial_progress=None):
        job_id = uuid.uuid4().hex
        cancel_event = threading.Event()
        with self._lock:
            if self._shutdown:
                raise ProfileManagerError("Background jobs are shut down.")
            self._prune_terminal_locked()
            self._jobs[job_id] = {
                "job_id": job_id,
                "label": str(label),
                "status": "queued",
                "progress": _json_safe(
                    initial_progress
                    if isinstance(initial_progress, dict)
                    else {"completed": 0, "total": 0}
                ),
                "result": None,
                "error": None,
                "cancel_requested": False,
                "_cancel_event": cancel_event,
            }
            # A worker may start immediately; _run waits for this registry lock
            # before it changes the newly-created job's state.
            self._executor.submit(self._run, job_id, worker, cancel_event)
        return job_id

    def _run(self, job_id, worker, cancel_event):
        with self._lock:
            job = self._jobs.get(job_id)
            if (
                job is None
                or job["status"] != "queued"
                or cancel_event.is_set()
            ):
                return
            job["status"] = "running"

        def progress(value):
            if isinstance(value, dict):
                self._set(job_id, progress=_json_safe(value))

        try:
            result = worker(cancel_event, progress)
            status = "cancelled" if cancel_event.is_set() else "completed"
            self._set(job_id, status=status, result=_json_safe(result))
        except Exception as error:  # bridge jobs must never kill the worker
            self._set(job_id, status="failed", error=str(error) or error.__class__.__name__)

    def _set(self, job_id, **changes):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.update(changes)
                if changes.get("status") not in {None, "queued", "running"}:
                    self._prune_terminal_locked()

    def _prune_terminal_locked(self):
        terminal = [
            job_id for job_id, job in self._jobs.items()
            if job["status"] not in {"queued", "running"}
        ]
        excess = len(terminal) - self.MAX_RETAINED_JOBS
        for job_id in terminal:
            if excess <= 0:
                break
            self._jobs.pop(job_id, None)
            excess -= 1

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                raise ProfileManagerError("Job was not found.")
            return {
                key: _json_safe(value)
                for key, value in job.items()
                if not key.startswith("_")
            }

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                raise ProfileManagerError("Job was not found.")
            job["cancel_requested"] = True
            job["_cancel_event"].set()
            if job["status"] == "queued":
                job["status"] = "cancelled"
                self._prune_terminal_locked()
            return self.get(job_id)

    def shutdown(self):
        with self._lock:
            if self._shutdown:
                wait_for_existing_shutdown = True
            else:
                wait_for_existing_shutdown = False
                self._shutdown = True
                for job in self._jobs.values():
                    if job["status"] not in {"queued", "running"}:
                        continue
                    job["cancel_requested"] = True
                    job["_cancel_event"].set()
                    if job["status"] == "queued":
                        job["status"] = "cancelled"
                self._prune_terminal_locked()
        if wait_for_existing_shutdown:
            self._shutdown_complete.wait()
            return
        try:
            # Mutating workers cooperate with their cancellation event and
            # finish the current atomic item before shutdown returns. This
            # prevents hidden profile writes after the UI has closed.
            self._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            self._shutdown_complete.set()


class ProxyDiagnostics:
    """Provider-isolated proxy/IP diagnostics with graceful fallbacks."""

    def __init__(self, ip_endpoint="https://api.ipify.org?format=json", geo_endpoint="https://ipwho.is/{ip}"):
        self.ip_endpoint = ip_endpoint
        self.geo_endpoint = geo_endpoint

    @staticmethod
    def _parsed(value):
        if isinstance(value, str):
            return proxy.parse_proxy_string(value)
        if not isinstance(value, dict):
            raise proxy.ProxyValidationError("Proxy input must be text or an object.")
        allowed = {"enabled", "scheme", "host", "port", "raw"}
        if any(key not in allowed for key in value):
            raise proxy.ProxyValidationError("Proxy settings contain an unsupported field.")
        if value.get("enabled") is False:
            return {"scheme": "http", "host": None, "port": None}
        parsed = proxy.parse_proxy_string(value.get("raw", "")) if value.get("raw") else None
        if parsed is not None:
            return parsed
        normalized = proxy.normalize_proxy_config(
            value.get("scheme"), value.get("host"), value.get("port")
        )
        if normalized is None:
            raise proxy.ProxyValidationError("Proxy configuration is incomplete or invalid.")
        return normalized

    def check(self, value, timeout=8, geolocation_provider=None):
        parsed = self._parsed(value)
        if parsed.get("host") is None:
            return {
                "alive": False,
                "status": "Dead",
                "error": "Provide a proxy endpoint before checking it.",
            }
        if parsed["scheme"] in {"socks4", "socks5"}:
            return {
                "alive": False,
                "status": "Dead",
                "error": "SOCKS checks require a SOCKS-capable optional provider; HTTP checks are supported in this build.",
            }

        host = parsed["host"]
        display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        proxy_uri = f"{parsed['scheme']}://{display_host}:{parsed['port']}"
        proxy_map = {"http": proxy_uri, "https": proxy_uri}
        opener = build_opener(ProxyHandler(proxy_map))
        started = time.monotonic()
        try:
            request = Request(self.ip_endpoint, headers={"User-Agent": "DiscordProfileManager/1.0"})
            with opener.open(request, timeout=max(1, min(int(timeout), 60))) as response:
                payload = json.loads(response.read().decode("utf-8"))
            outbound_ip = payload.get("ip") if isinstance(payload, dict) else None
            if not isinstance(outbound_ip, str) or not outbound_ip.strip():
                raise ValueError("IP provider returned no outbound IP.")
            outbound_ip = outbound_ip.strip()
            result = {
                "alive": True,
                "status": "Alive",
                "outbound_ip": outbound_ip,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "country": None,
                "city": None,
                "provider": None,
                "asn": None,
                "error": None,
            }
            try:
                geo = (
                    geolocation_provider(outbound_ip, timeout)
                    if callable(geolocation_provider)
                    else self._geolocate(outbound_ip, timeout)
                )
                if isinstance(geo, dict):
                    result.update({
                        "country": geo.get("country") or geo.get("country_name"),
                        "city": geo.get("city"),
                        "provider": geo.get("isp") or geo.get("org") or geo.get("provider"),
                        "asn": geo.get("asn"),
                    })
            except Exception:
                # IP health remains useful even when geography is unavailable.
                result["geography_warning"] = "Location information is unavailable."
            return result
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            message = str(error.reason if isinstance(error, HTTPError) else error)
            return {
                "alive": False,
                "status": "Dead",
                "latency_ms": round((time.monotonic() - started) * 1000),
                "error": message[:240] or "Proxy check timed out.",
            }

    def _geolocate(self, ip_address, timeout):
        url = self.geo_endpoint.format(ip=quote(ip_address, safe="."))
        with urlopen(Request(url, headers={"User-Agent": "DiscordProfileManager/1.0"}), timeout=max(1, min(int(timeout), 60))) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("success") is False:
            raise ValueError("Geography provider returned no location.")
        return payload


class ProductAPI:
    """The only Python object intentionally exposed to JavaScript."""

    def __init__(self, composition=None, *, profile_service=None, account_service=None,
                 credential_service=None, launcher=None, extension_service=None,
                 process_inspector=None, diagnostics=None, jobs=None):
        if composition is not None:
            profile_service = profile_service or composition.profile_service
            account_service = account_service or composition.account_service
            credential_service = credential_service or getattr(composition, "credential_service", None)
            launcher = launcher or composition.launcher
            extension_service = extension_service or composition.extension_service
            process_inspector = process_inspector or composition.process_inspector
        self.profile_service = profile_service
        self.account_service = account_service
        self.credential_service = credential_service or account_service
        self.launcher = launcher
        self.extension_service = extension_service
        self.process_inspector = process_inspector
        self.diagnostics = diagnostics or ProxyDiagnostics()
        self.jobs = jobs or JobManager()

    def _records(self):
        records = self.profile_service.get_profile_metadata()
        if len(records) > MAX_DISPLAYED_PROFILES:
            raise ProfileManagerError(
                f"The catalog contains more than {MAX_DISPLAYED_PROFILES:,} displayed profiles."
            )
        return list(records)

    def _status(self, profile_id, record=None):
        try:
            # Status polling already has the catalog record.  Reuse its
            # directory mapping so a two-second poll does not reload the full
            # catalog once per row.
            try:
                path = self.profile_service.get_profile_dir(profile_id, record=record)
            except TypeError:
                # Compatibility with small injected service doubles.
                path = self.profile_service.get_profile_dir(profile_id)
            if not Path(path).is_dir():
                return "Error"
            if self.process_inspector and self.process_inspector.using_directory(path):
                return "Running"
            return "Closed"
        except Exception:
            return "Error"

    def _status_map(self, records, profile_ids=None):
        """Resolve status for many records with at most one process walk."""
        requested = None
        if profile_ids is not None:
            requested = {str(value) for value in profile_ids}
        selected = [
            record for record in records
            if requested is None or record.get("profile_id") in requested
        ]
        statuses = {}
        paths = {}
        for record in selected:
            profile_id = record["profile_id"]
            try:
                try:
                    path = self.profile_service.get_profile_dir(
                        profile_id, record=record
                    )
                except TypeError:
                    path = self.profile_service.get_profile_dir(profile_id)
                path = Path(path)
                if not path.is_dir():
                    statuses[profile_id] = "Error"
                else:
                    paths[profile_id] = path.resolve()
            except Exception:
                statuses[profile_id] = "Error"

        bulk_checker = getattr(self.process_inspector, "using_directories", None)
        if paths and callable(bulk_checker):
            try:
                running = {Path(value).resolve() for value in bulk_checker(paths.values())}
            except Exception:
                running = None
            if running is not None:
                for profile_id, path in paths.items():
                    statuses[profile_id] = "Running" if path in running else "Closed"
                return statuses

        for profile_id in paths:
            statuses[profile_id] = self._status(profile_id, next(
                record for record in selected if record["profile_id"] == profile_id
            ))
        return statuses

    def _account_email(self, profile_id, record):
        # Product records already carry the safe account association.  It is
        # authoritative for the table and avoids re-reading profile-local
        # Autofill files (and the catalog they are resolved through) once per
        # row during a full refresh.
        account = record.get("account") if isinstance(record, dict) else None
        if isinstance(account, dict):
            email = account.get("email") or account.get("email_identifier")
            if isinstance(email, str) and email.strip():
                return email.strip()
            label = account.get("label") or account.get("account_label")
            if isinstance(label, str) and label.strip():
                return label.strip()
        try:
            try:
                account = self.credential_service.get_account(
                    profile_id, record=record
                )
            except TypeError:
                account = self.credential_service.get_account(profile_id)
        except Exception:
            account = record.get("account") if isinstance(record, dict) else None
        if not isinstance(account, dict):
            return None
        email = account.get("email") or account.get("email_identifier")
        if isinstance(email, str) and email.strip():
            return email.strip()
        label = account.get("label") or account.get("account_label")
        return label.strip() if isinstance(label, str) and label.strip() else None

    @staticmethod
    def _environment_view(record, position=None):
        preset, config = environment.effective_environment(record)
        product_details = None
        if config.get("environment_schema") == environment.PRODUCT_ENVIRONMENT_SCHEMA:
            product_details = environment.product_environment_details(record, position=position)
            config = {
                **config,
                "window_width": product_details["window_geometry"]["width"],
                "window_height": product_details["window_geometry"]["height"],
            }
        label = {
            environment.ENVIRONMENT_AUTO: "Auto",
            environment.ENVIRONMENT_DESKTOP: "Desktop",
            environment.ENVIRONMENT_DEFAULT_DESKTOP: "Desktop",
            environment.ENVIRONMENT_WINDOWS_CHROMIUM: "Desktop",
            environment.ENVIRONMENT_ANDROID_CHROMIUM: "Mobile",
            environment.ENVIRONMENT_CUSTOM: "Custom",
            environment.ENVIRONMENT_GENERATED: "Auto",
        }.get(preset, environment.preset_label(preset))
        result = {
            "preset": preset,
            "label": label,
            "generated_family": config.get("generated_family"),
            "generated_revision": config.get("generated_revision"),
            "environment_seed": config.get("environment_seed"),
            "environment_signature": config.get("environment_signature"),
            "signature": config.get("environment_signature"),
            "user_agent": config.get("user_agent"),
            "language": config.get("language"),
            "language_order": list(config.get("language_order") or ()),
            "timezone": config.get("timezone"),
            "region": config.get("region"),
            "windows_timezone_key": config.get("windows_timezone_key"),
            "window_width": config.get("window_width", config.get("viewport_width")),
            "window_height": config.get("window_height", config.get("viewport_height")),
            "mobile_mode": bool(config.get("mobile_mode", False)),
            "touch_mode": bool(config.get("touch_mode", False)),
            "window_size_policy": config.get("window_size_policy"),
            "generated": preset == environment.ENVIRONMENT_GENERATED,
            "timezone_applied": False,
            "unsupported_mobile_emulation": bool(
                preset == environment.ENVIRONMENT_ANDROID_CHROMIUM
            ),
        }
        if product_details is not None:
            result.update({
                "field_sources": product_details.get("field_sources", {}),
                "runtime_version": product_details.get("runtime_version"),
                "window_geometry": product_details.get("window_geometry"),
                "generated": True,
                "unsupported_mobile_emulation": product_details.get(
                    "unsupported_mobile_emulation", False
                ),
            })
        return result

    def _dto(self, record, stt, status=None):
        profile_id = record["profile_id"]
        account = self._account_email(profile_id, record)
        proxy_state = proxy.effective_proxy(record)
        return {
            "profile_id": profile_id,
            "stt": f"{stt:04d}",
            "name": record.get("display_name") or profile_id,
            "account": account,
            "has_account": bool(account),
            "environment": self._environment_view(record, position=stt),
            "proxy": {
                "enabled": bool(proxy_state.get("enabled")),
                "scheme": proxy_state.get("scheme"),
                "host": proxy_state.get("host"),
                "port": proxy_state.get("port"),
            },
            "status": self._status(profile_id, record) if status is None else status,
            "last_opened": record.get("last_opened_at"),
            "created_at": record.get("created_at"),
        }

    def initialize_catalog(self):
        """Reconcile and publish the application catalog for the loading splash.

        This is the controlled startup write that used to run before the window
        opened. The splash runs it as a critical task, so a failure is shown
        instead of opening an empty table.
        """
        catalog = self.profile_service.initialize_metadata()
        return {"profiles": len(catalog["profiles"])}

    def report_startup_warning(self, task_id, message):
        """Log one non-critical startup failure that the splash reported."""
        if str(task_id) not in STARTUP_TASK_IDS:
            return {"logged": False}
        text = " ".join(str(message or "").split())[:200]
        _LOGGER.warning("Startup task %s reported a problem: %s", task_id, text)
        return {"logged": True}

    def list_profiles(self, search="", sort="stt", reverse=False, status=None):
        records = self._records()
        statuses = self._status_map(records)
        # STT is the position in table order, so the records are sorted before they are numbered.
        rows = [
            self._dto(record, position, statuses.get(record["profile_id"], "Error"))
            for position, record in table_order(records)
        ]
        needle = str(search or "").strip().casefold()
        if needle:
            rows = [
                row for row in rows
                if needle in " ".join(str(row.get(field) or "") for field in (
                    "stt", "profile_id", "name", "account", "status",
                )).casefold()
                or needle in str(row["proxy"].get("host") or "").casefold()
            ]
        if status in {"Running", "Closed", "Error"}:
            rows = [row for row in rows if row["status"] == status]
        sort_key = str(sort or "stt").casefold()
        keys = {
            "stt": lambda row: row["stt"],
            "id": lambda row: row["profile_id"].casefold(),
            "name": lambda row: row["name"].casefold(),
            "account": lambda row: str(row["account"] or "").casefold(),
            "status": lambda row: row["status"],
        }
        if sort_key == "last_opened":
            # Missing timestamps are always last. ISO-8601 UTC timestamps sort
            # chronologically as strings, and STT provides a stable tie-break.
            opened = [row for row in rows if row.get("last_opened")]
            unopened = [row for row in rows if not row.get("last_opened")]
            opened.sort(
                key=lambda row: str(row["last_opened"]),
                reverse=not bool(reverse),
            )
            unopened.sort(key=lambda row: row["stt"])
            rows = opened + unopened
        else:
            rows.sort(key=keys.get(sort_key, keys["stt"]), reverse=bool(reverse))
        return _json_safe(rows)

    def display_order(self):
        """Return every profile's STT in table order, for the table to take after a change that moves rows."""
        records = self._records()
        return _json_safe([
            {"profile_id": record["profile_id"], "stt": f"{position:04d}"}
            for position, record in table_order(records)
        ])

    def get_profile(self, profile_id):
        records = self._records()
        statuses = self._status_map(records, [profile_id])
        for position, record in table_order(records):
            if record.get("profile_id") == profile_id:
                return _json_safe(self._dto(
                    record, position, statuses.get(profile_id, "Error")
                ))
        raise ProfileManagerError("Profile was not found.")

    def refresh_status(self, profile_ids=None):
        """Return only local Chromium status fields for the lightweight poller."""
        records = self._records()
        if profile_ids is not None and not isinstance(profile_ids, (list, tuple, set)):
            profile_ids = [profile_ids]
        statuses = self._status_map(records, profile_ids)
        return _json_safe([
            {
                "profile_id": record["profile_id"],
                "status": statuses.get(record["profile_id"], "Error"),
            }
            for record in records
            if record["profile_id"] in statuses
        ])

    def _summaries_for_ids(self, profile_ids):
        """Return complete display rows for only the requested stable IDs."""
        requested = [str(value) for value in profile_ids]
        records = self._records()
        by_id = {record["profile_id"]: (position, record)
                 for position, record in table_order(records)}
        statuses = self._status_map(records, requested)
        rows = []
        for profile_id in requested:
            item = by_id.get(profile_id)
            if item is None:
                continue
            index, record = item
            rows.append(self._dto(
                record, index, statuses.get(profile_id, "Error")
            ))
        return _json_safe(rows)

    def _set_credential_account(
        self, profile_id, account_input, *, parsed_account=None,
        extensions_ready=False, skip_running_check=False,
    ):
        setter = getattr(self.credential_service, "set_legacy_account", None)
        if not callable(setter):
            setter = getattr(self.credential_service, "set_account", None)
        if not callable(setter):
            raise ProfileManagerError("The Autofill account workflow is unavailable.")
        if getattr(setter, "__name__", "") == "set_legacy_account":
            options = {
                "parsed_account": parsed_account,
                "extensions_ready": extensions_ready,
            }
            if skip_running_check:
                options["skip_running_check"] = True
            return setter(
                profile_id,
                account_input,
                **options,
            )
        return setter(profile_id, account_input)

    def _remove_account(self, profile_id):
        remover = getattr(self.credential_service, "remove_account", None)
        if not callable(remover):
            raise ProfileManagerError("Account removal is unavailable.")
        return remover(profile_id)

    @staticmethod
    def _proxy_payload(value):
        if value is None:
            return None
        if isinstance(value, str):
            parsed = proxy.parse_proxy_string(value)
            return {"enabled": True, **parsed}
        if not isinstance(value, dict):
            raise proxy.ProxyValidationError("Proxy settings must be an object or endpoint text.")
        allowed = {"enabled", "scheme", "host", "port"}
        if any(key not in allowed for key in value):
            raise proxy.ProxyValidationError("Proxy settings contain an unsupported field.")
        enabled = value.get("enabled", True)
        if enabled is False:
            return {"enabled": False}
        if enabled is not True:
            raise proxy.ProxyValidationError("Proxy state must be Enabled or Off.")
        normalized = proxy.normalize_proxy_config(
            value.get("scheme"), value.get("host"), value.get("port")
        )
        if normalized is None:
            raise proxy.ProxyValidationError("Proxy configuration is incomplete or invalid.")
        return {"enabled": True, **normalized}

    @staticmethod
    def _environment_request(payload):
        if isinstance(payload, dict):
            if isinstance(payload.get("environment"), dict):
                payload = payload["environment"]
            return dict(payload)
        return {"preset": payload}

    def _persist_product_environment(
        self, profile_id, payload=None, *, force_generate=False, creating=False,
        system_settings=None, proxy_payload=None,
    ):
        """Persist a truthful product environment without invoking Chromium."""
        request = self._environment_request(payload or {"preset": "Auto"})
        preset = request.get("preset", request.get("environment_preset", "Auto"))
        normalized = environment.normalize_environment_preset(preset)
        record = self.profile_service.get_profile_record(profile_id)
        previous = environment.normalize_environment_config(
            record.get("environment_config")
        ) or {}
        previous_product = previous.get("environment_schema") == environment.PRODUCT_ENVIRONMENT_SCHEMA
        current_family = previous.get("generated_family")
        requested_family = environment.product_environment_preset(normalized)
        meaningful_fields = {
            key: value for key, value in request.items()
            if key not in {"preset", "environment_preset"}
        }

        should_generate = creating or force_generate or not previous_product
        if normalized == environment.ENVIRONMENT_AUTO:
            generated = None
            target_preset = environment.ENVIRONMENT_AUTO
        elif normalized == environment.ENVIRONMENT_CUSTOM:
            should_generate = should_generate or bool(meaningful_fields)
            if should_generate:
                generated = environment.product_custom_environment(
                    profile_id,
                    request,
                    previous_config=previous,
                    system_settings=system_settings,
                )
                target_preset = environment.ENVIRONMENT_CUSTOM
            else:
                generated = previous
                target_preset = environment.ENVIRONMENT_CUSTOM
        else:
            should_generate = should_generate or requested_family != current_family
            if should_generate:
                generated = environment.generate_product_environment(
                    profile_id,
                    normalized,
                    previous_config=previous,
                    regenerate=force_generate,
                    system_settings=system_settings,
                )
            else:
                generated = previous
            target_preset = normalized
        self.profile_service.save_runtime_settings(
            profile_id,
            target_preset,
            generated,
            proxy_config=proxy_payload,
        )
        return generated

    def _apply_options(self, profile_id, *, environment_payload=None, proxy_payload=None):
        normalized_proxy = self._proxy_payload(proxy_payload)
        if environment_payload is not None:
            self._persist_product_environment(
                profile_id,
                environment_payload,
                proxy_payload=normalized_proxy,
            )
        elif normalized_proxy is not None:
            current = self.profile_service.get_profile_record(profile_id)
            self.profile_service.save_runtime_settings(
                profile_id,
                current.get("environment_preset", "Desktop"),
                current.get("environment_config"),
                proxy_config=normalized_proxy,
            )

    def _create_profile_internal(
        self, display_name, account_input=None, *, parsed_account=None,
        environment_payload=None, proxy_payload=None, extension_sources=None,
        system_settings=None, skip_running_check=False,
    ):
        profile_id = self.profile_service.create_profile(display_name)
        try:
            # Staging is a pure filesystem/preferences operation; it is never a
            # browser probe and therefore cannot create a transient Chromium
            # window.  A prepared source cache avoids re-scanning immutable
            # master extension files for every imported profile.
            self.extension_service.ensure_required_extensions(
                profile_id, source_cache=extension_sources
            )
            if account_input:
                self._set_credential_account(
                    profile_id,
                    account_input,
                    parsed_account=parsed_account,
                    extensions_ready=True,
                    skip_running_check=skip_running_check,
                )
            self._persist_product_environment(
                profile_id,
                environment_payload or {"preset": "Auto"},
                creating=True,
                system_settings=system_settings,
            )
            if proxy_payload is not None:
                self._apply_options(profile_id, proxy_payload=self._proxy_payload(proxy_payload))
        except Exception:
            try:
                self.profile_service.delete_profile(profile_id)
            except Exception:
                pass
            raise
        return profile_id

    def create_profile(self, name=None, account_input=None, environment_payload=None, proxy_payload=None):
        parsed = parse_account_input(account_input) if account_input else None
        display_name = (name or (derive_profile_name(parsed["email"]) if parsed else "Profile")).strip()
        if not display_name:
            display_name = "Profile"
        extension_sources = self.extension_service.prepare_required_extension_sources()
        profile_id = self._create_profile_internal(
            display_name,
            account_input,
            parsed_account=parsed,
            environment_payload=environment_payload,
            proxy_payload=proxy_payload,
            extension_sources=extension_sources,
        )
        return self.get_profile(profile_id)

    def update_profile(self, profile_id, name=None, account_input=None, remove_account=False,
                       environment_payload=None, proxy_payload=None):
        parsed_account = (
            parse_account_input(account_input)
            if account_input is not None and not remove_account
            else None
        )
        normalized_proxy = self._proxy_payload(proxy_payload)
        if environment_payload is not None:
            request = self._environment_request(environment_payload)
            environment.normalize_environment_preset(
                request.get("preset", request.get("environment_preset", "Auto"))
            )
        if name is not None:
            self.profile_service.rename_profile(profile_id, name)
        if remove_account:
            self._remove_account(profile_id)
        elif account_input is not None:
            self._set_credential_account(
                profile_id,
                account_input,
                parsed_account=parsed_account,
            )
        if environment_payload is not None or proxy_payload is not None:
            self._apply_options(
                profile_id,
                environment_payload=environment_payload,
                proxy_payload=normalized_proxy,
            )
        return self.get_profile(profile_id)

    def rename_profile(self, profile_id, name):
        self.profile_service.rename_profile(profile_id, name)
        return self.get_profile(profile_id)

    def delete_profiles(self, profile_ids, confirmed=False):
        if not isinstance(profile_ids, (list, tuple, set)):
            profile_ids = [profile_ids]
        profile_ids = [str(value) for value in profile_ids if value]
        if not confirmed:
            return {
                "requires_confirmation": True,
                "requested": len(profile_ids),
                "deleted": 0,
                "failed": 0,
                "remaining": len(self._records()),
                "errors": [],
                "results": [],
            }

        def request_close(profile_id):
            # The launcher owns handles for processes started by this manager.
            # Test/integration hosts may expose the same hook on the inspector.
            for owner in (self.launcher, self.process_inspector):
                closer = getattr(owner, "close_profile", None) if owner is not None else None
                if callable(closer):
                    closer(profile_id)
                    return

        try:
            result = self.profile_service.delete_profiles(
                profile_ids,
                close_callback=request_close,
            )
        except AttributeError:
            # Keep compatibility with small injected profile-service doubles
            # that predate the bulk service operation.
            results = []
            for profile_id in profile_ids:
                try:
                    self.profile_service.delete_profile(profile_id)
                    results.append({"profile_id": profile_id, "status": "deleted", "error": None})
                except Exception as error:
                    results.append({"profile_id": profile_id, "status": "failed", "error": str(error)[:240]})
            result = {
                "results": results,
                "requested": len(profile_ids),
                "deleted": sum(item["status"] == "deleted" for item in results),
                "failed": sum(item["status"] != "deleted" for item in results),
            }
        errors = [
            {"profile_id": item["profile_id"], "error": item.get("error") or "Deletion failed."}
            for item in result.get("results", [])
            if item.get("status") != "deleted"
        ]
        result.update({
            "requires_confirmation": False,
            "errors": errors,
            "failed": int(result.get("failed", len(errors))),
            "deleted_profile_ids": [
                item["profile_id"] for item in result.get("results", [])
                if item.get("status") == "deleted"
            ],
        })
        return _json_safe(result)

    def delete_profile(self, profile_id, confirmed=False):
        return self.delete_profiles([profile_id], confirmed=confirmed)

    def launch_profile(self, profile_id):
        started = self.launcher.launch_discord(profile_id)
        return {"profile": self.get_profile(profile_id), "started": bool(started), "already_running": not started}

    def launch_batch(self, profile_ids, delay=0.0):
        if not isinstance(profile_ids, (list, tuple)) or not profile_ids:
            raise ProfileManagerError("Select at least one profile to launch.")
        try:
            delay = float(delay)
        except (TypeError, ValueError):
            raise ProfileManagerError("Launch delay must be a number of seconds.")
        if not 0 <= delay <= 60:
            raise ProfileManagerError("Launch delay must be between 0 and 60 seconds.")
        profile_ids = [str(profile_id) for profile_id in profile_ids]

        def worker(cancel_event, progress):
            results = []
            opened_profile_ids = []
            failed = 0
            total = len(profile_ids)
            for index, profile_id in enumerate(profile_ids):
                if cancel_event.is_set():
                    break
                try:
                    started = self.launcher.launch_discord(profile_id)
                    results.append({
                        "profile_id": profile_id,
                        "status": "launched" if started else "already_running",
                    })
                    if started:
                        opened_profile_ids.append(profile_id)
                except Exception as error:
                    failed += 1
                    results.append({
                        "profile_id": profile_id,
                        "status": "error",
                        "error": str(error)[:240],
                    })
                progress({
                    "completed": len(results), "total": total,
                    "current_profile_id": profile_id, "results": results,
                })
                if index < total - 1 and delay:
                    cancel_event.wait(delay)
            return {
                "requested": total,
                "completed": len(results),
                "succeeded": len(results) - failed,
                "failed": failed,
                "cancelled": cancel_event.is_set(),
                "results": results,
                "profiles": self._summaries_for_ids(opened_profile_ids),
            }

        return self.jobs.start("batch-launch", worker)

    def cancel_batch(self, job_id):
        return self.jobs.cancel(job_id)

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    @staticmethod
    def _safe_import_message(error, raw_line=None):
        """Keep account values out of import progress and line errors."""
        message = str(error)[:500] if error else "Could not import this line."
        values = [raw_line] if isinstance(raw_line, str) else []
        values.extend(part for part in str(raw_line or "").split(":") if part)
        for value in values:
            message = message.replace(value, "[redacted]")
        return message[:240] or "Could not import this line."

    @classmethod
    def _parse_import_records(cls, text):
        records = []
        for line_number, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            record = {
                "line": line_number,
                "raw": line,
                "parsed": None,
                "parse_error": None,
            }
            try:
                record["parsed"] = parse_account_input(line)
            except Exception as error:
                record["parse_error"] = cls._safe_import_message(error, line)
            records.append(record)
        return records

    def import_accounts_txt(self, text):
        if not isinstance(text, str):
            raise ProfileManagerError("Import content must be text.")

        # Parse the complete input before the asynchronous job starts.  This
        # fixes the progress contract and means the worker never discovers a
        # changing total while it is creating profiles.
        records = self._parse_import_records(text)
        total = len(records)
        extension_sources = self.extension_service.prepare_required_extension_sources()
        system_settings = environment.windows_system_environment()
        # Reading the work area is intentionally batch-scoped.  It is a
        # read-only invariant for this job and avoids repeating Win32 calls if
        # a future environment generator needs the physical bounds.
        work_area = environment.get_windows_work_area()
        batch_context = {
            "extension_sources": extension_sources,
            "system_settings": system_settings,
            "work_area": work_area,
            "runtime_version": environment.CHROMIUM_VERSION,
        }
        initial_progress = {
            "completed": 0,
            "total": total,
            "current_line": 0,
            "current_profile": None,
            "status": "queued",
            "message": "Import queued.",
        }

        def worker(cancel_event, progress):
            summary = {"total": total, "created": 0, "skipped": 0, "failed": 0, "errors": []}
            created_profile_ids = []
            with self.profile_service.batch_operation():
                for record in records:
                    line_number = record["line"]
                    current_profile = None
                    if cancel_event.is_set():
                        summary["skipped"] += 1
                        status = "skipped"
                        message = "Skipped because the import was cancelled."
                    elif record["parse_error"]:
                        summary["failed"] += 1
                        status = "failed"
                        message = record["parse_error"]
                        summary["errors"].append({
                            "line": line_number,
                            "message": message,
                        })
                    else:
                        try:
                            parsed = record["parsed"]
                            name = derive_profile_name(parsed["email"])
                            current_profile = self._create_profile_internal(
                                name,
                                record["raw"],
                                parsed_account=parsed,
                                environment_payload={
                                    "preset": environment.ENVIRONMENT_AUTO
                                },
                                extension_sources=batch_context["extension_sources"],
                                system_settings=batch_context["system_settings"],
                                skip_running_check=True,
                            )
                            summary["created"] += 1
                            created_profile_ids.append(current_profile)
                            status = "created"
                            message = "Profile created."
                        except Exception as error:
                            summary["failed"] += 1
                            status = "failed"
                            message = self._safe_import_message(error, record["raw"])
                            summary["errors"].append({
                                "line": line_number,
                                "message": message,
                            })
                    completed = summary["created"] + summary["skipped"] + summary["failed"]
                    progress({
                        "completed": completed,
                        "total": total,
                        "current_line": line_number,
                        "current_profile": current_profile,
                        "status": status,
                        "message": message,
                        "created": summary["created"],
                        "skipped": summary["skipped"],
                        "failed": summary["failed"],
                    })
            # The terminal result is a delta: only successfully committed
            # profiles are materialized for the table.  It is intentionally
            # built after batch_operation publishes the catalog.
            summary["profiles"] = self._summaries_for_ids(created_profile_ids)
            return summary

        return self.jobs.start(
            "account-import",
            worker,
            initial_progress=initial_progress,
        )

    def import_accounts_txt_sync(self, text):
        """Run the importer directly for scripts/tests that already own a worker."""
        job_id = self.import_accounts_txt(text)
        while True:
            state = self.get_job(job_id)
            if state["status"] not in {"queued", "running"}:
                if state["status"] == "failed":
                    raise ProfileManagerError(state.get("error") or "Account import failed.")
                return state.get("result") or {}
            time.sleep(0.01)

    def _credential_record(self, profile_id):
        """Read credentials only for the explicit user-requested export path."""
        try:
            reader = getattr(self.credential_service, "get_local_credentials", None)
            account = reader(profile_id) if callable(reader) else self.credential_service.get_account(profile_id)
        except Exception:
            account = None
        if not isinstance(account, dict):
            return {}
        return {
            "email": account.get("email") or account.get("email_identifier") or "",
            "password": account.get("password") or "",
            "totp_secret": account.get("totp_secret") or account.get("totp") or "",
            "discord_token": (
                account.get("discord_token")
                or account.get("token")
                or account.get("authorization")
                or ""
            ),
            "account_mode": account.get("mode") or "",
            "account_label": account.get("label") or account.get("account_label") or "",
        }

    def _export_rows(self, profile_ids=None):
        """Build complete account records only for the explicit export action."""
        records = self._records()
        stt_by_id = {record["profile_id"]: f"{position:04d}" for position, record in table_order(records)}
        if profile_ids is not None:
            if not isinstance(profile_ids, (list, tuple, set)):
                profile_ids = [profile_ids]
            requested = [str(value) for value in profile_ids if value]
            unknown = [value for value in requested if value not in stt_by_id]
            if unknown:
                raise ProfileManagerError("One or more selected profiles were not found.")
            record_map = {record["profile_id"]: record for record in records}
            records = [record_map[value] for value in requested]

        result = []
        for record in records:
            profile_id = record["profile_id"]
            credentials = self._credential_record(profile_id)
            account_metadata = record.get("account") if isinstance(record.get("account"), dict) else {}
            env = self._environment_view(record, position=int(stt_by_id[profile_id]))
            proxy_state = proxy.effective_proxy(record)
            row = {
                "profile_id": profile_id,
                "stt": stt_by_id[profile_id],
                "display_name": record.get("display_name") or profile_id,
                "email": credentials.get("email") or account_metadata.get("email", ""),
                "password": credentials.get("password", ""),
                "totp_secret": credentials.get("totp_secret", ""),
                "has_2fa": bool(credentials.get("totp_secret")),
                "discord_token": credentials.get("discord_token", ""),
                "account_mode": credentials.get("account_mode") or account_metadata.get("mode", ""),
                "account_label": credentials.get("account_label") or account_metadata.get("label", ""),
                "environment_mode": env.get("label") or env.get("preset") or "",
                "environment_locale": env.get("language") or "",
                "environment_language_order": ",".join(env.get("language_order") or ()),
                "environment_timezone": env.get("timezone") or "",
                "environment_region": env.get("region") or "",
                "environment_user_agent": env.get("user_agent") or "",
                "environment_mobile": bool(env.get("mobile_mode")),
                "environment_touch": bool(env.get("touch_mode")),
                "environment_signature": env.get("environment_signature") or "",
                "proxy_enabled": bool(proxy_state.get("enabled")),
                "proxy_scheme": proxy_state.get("scheme") or "",
                "proxy_host": proxy_state.get("host") or "",
                "proxy_port": proxy_state.get("port") or "",
                "created_at": record.get("created_at") or "",
                "updated_at": record.get("updated_at") or record.get("created_at") or "",
                "last_used": record.get("last_opened_at") or "",
                "status": self._status(profile_id, record),
            }
            result.append({key: row.get(key, "") for key in EXPORT_COLUMNS})
        return result

    @staticmethod
    def _export_timestamp():
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def export_json(self, profile_ids=None):
        rows = self._export_rows(profile_ids)
        content = json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
        return {
            "filename": f"discord_accounts_{self._export_timestamp()}.json",
            "content": content,
            "count": len(rows),
            "columns": list(EXPORT_COLUMNS),
            "contains_sensitive_credentials": True,
        }

    def export_csv(self, profile_ids=None):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        rows = self._export_rows(profile_ids)
        writer.writerows(rows)
        return {
            "filename": f"discord_accounts_{self._export_timestamp()}.csv",
            "content": output.getvalue(),
            "count": len(rows),
            "columns": list(EXPORT_COLUMNS),
            "contains_sensitive_credentials": True,
        }

    def export_txt(self, profile_ids=None):
        rows = self._export_rows(profile_ids)

        def escape(value):
            text = "" if value is None else str(value)
            return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r", "\\r").replace("\n", "\\n")

        content = "".join(
            "|".join(escape(row.get(column, "")) for column in EXPORT_COLUMNS) + "\n"
            for row in rows
        )
        return {
            "filename": f"discord_accounts_{self._export_timestamp()}.txt",
            "content": content,
            "count": len(rows),
            "columns": list(EXPORT_COLUMNS),
            "contains_sensitive_credentials": True,
        }

    def save_account_export(self, kind="json", profile_ids=None):
        """Show a native save dialog and write the selected complete records."""
        kind = str(kind or "json").casefold()
        exporters = {"json": self.export_json, "csv": self.export_csv, "txt": self.export_txt}
        if kind not in exporters:
            raise ProfileManagerError("Export format must be JSON, CSV, or TXT.")
        export = exporters[kind](profile_ids)
        try:
            import webview
            windows = getattr(webview, "windows", ())
            window = windows[0] if windows else None
            save_dialog = getattr(webview, "SAVE_DIALOG", 2)
            if window is None or not callable(getattr(window, "create_file_dialog", None)):
                raise ProfileManagerError("The native save dialog is unavailable.")
            file_type = {
                "json": "JSON files (*.json)",
                "csv": "CSV files (*.csv)",
                "txt": "Text files (*.txt)",
            }[kind]
            selected = window.create_file_dialog(
                save_dialog,
                save_filename=export["filename"],
                file_types=(file_type,),
            )
        except ImportError as error:
            raise ProfileManagerError("The native save dialog is unavailable.") from error
        if not selected:
            return {"cancelled": True, "saved": False, "count": export["count"]}
        destination = selected[0] if isinstance(selected, (tuple, list)) else selected
        destination = Path(destination)
        if destination.suffix.casefold() != f".{kind}":
            destination = destination.with_suffix(f".{kind}")
        try:
            destination.write_text(export["content"], encoding="utf-8", newline="")
        except (OSError, UnicodeError) as error:
            raise ProfileManagerError("Could not write the account export file.") from error
        return {
            "cancelled": False,
            "saved": True,
            "filename": destination.name,
            "path": str(destination),
            "count": export["count"],
            "contains_sensitive_credentials": True,
        }

    def parse_proxy(self, value):
        parsed = proxy.parse_proxy_string(value)
        return _json_safe({
            "scheme": parsed["scheme"], "host": parsed["host"], "port": parsed["port"],
        })

    def check_proxy(self, value, timeout=8):
        return self.jobs.start(
            "proxy-check",
            lambda cancel_event, progress: self.diagnostics.check(value, timeout=timeout),
        )

    def generate_environment(self, profile_id, preset="Desktop", custom=None):
        key = re.sub(r"[\s_/-]+", "-", str(preset or "Desktop").strip().casefold())
        if key == "auto":
            target = environment.ENVIRONMENT_AUTO
            label = "Auto"
        elif key in {"desktop", "default", "windows", "windows-chromium"}:
            target = environment.ENVIRONMENT_WINDOWS_CHROMIUM
            label = "Desktop"
        elif key in {"mobile", "android", "android-chromium"}:
            target = environment.ENVIRONMENT_ANDROID_CHROMIUM
            label = "Mobile"
        elif key in {"custom", "manual"}:
            target = environment.ENVIRONMENT_CUSTOM
            label = "Custom"
        elif key in {"generated", "random", "generated-random"}:
            target = environment.ENVIRONMENT_GENERATED
            label = "Generated"
        else:
            raise ProfileManagerError("Environment must be Auto, Desktop, Mobile, Custom, or Generated.")
        payload = {"preset": target}
        if target == environment.ENVIRONMENT_CUSTOM and isinstance(custom, dict):
            payload.update(custom)
        self._persist_product_environment(
            profile_id,
            payload,
            force_generate=True,
        )
        result = self.get_profile(profile_id)
        result["generator_preset"] = label
        return result

    def get_runtime_info(self):
        browser_path = Path(self.profile_service.paths.browser_exe)
        # Reading the Windows version resource is side-effect free.  In
        # particular, runtime information must never execute chrome.exe just
        # because the manager refreshed or opened an editor.
        detected_version = environment.chromium_file_version(browser_path)
        if detected_version and not detected_version.startswith(environment.CHROMIUM_VERSION.split(".", 1)[0]):
            detected_version = None
        return {
            "browser_available": browser_path.is_file(),
            "browser_version": detected_version or environment.CHROMIUM_VERSION,
            "version_source": "detected" if detected_version else "expected bundled runtime",
            "detection_method": "Windows version resource; no browser launch",
            "runtime_name": "Ungoogled Chromium",
            "browser_path_label": "browser/chrome.exe",
            "discord_url": "https://discord.com/app",
        }

    def get_extension_policy(self):
        state = self.extension_service.get_registry_state()
        return _json_safe({
            "required": [
                {key: item.get(key) for key in ("name", "display_name", "available", "required", "enabled")}
                for item in state.get("built_ins", [])
            ],
            "optional": [
                {key: item.get(key) for key in ("name", "display_name", "available", "required", "enabled")}
                for item in state.get("optional", [])
            ],
            "quarantined": [
                {key: item.get(key) for key in ("name", "reason", "enabled")}
                for item in state.get("quarantined", [])
            ],
        })

    def get_ui_preferences(self):
        """Read non-sensitive UI preferences from application-owned config."""
        path = self.profile_service.paths.ui_preferences_json
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        allowed_columns = {"account", "environment", "last_opened"}
        raw_columns = payload.get("visible_columns")
        visible = (
            [value for value in dict.fromkeys(map(str, raw_columns)) if value in allowed_columns]
            if isinstance(raw_columns, list)
            else ["account", "environment", "last_opened"]
        )
        saved_theme = str(payload.get("theme", "dark")).casefold()
        # Older product builds persisted `system`. Keep those files readable
        # without exposing a non-deterministic third appearance mode.
        theme = "dark" if saved_theme == "system" else saved_theme
        if theme not in {"light", "dark"}:
            theme = "dark"
        result = {
            "theme": theme,
            "reduce_motion": bool(payload.get("reduce_motion", False)),
            "visible_columns": visible,
        }
        return _json_safe(result)

    def save_ui_preferences(self, preferences):
        """Validate and atomically persist presentation-only preferences."""
        if not isinstance(preferences, dict):
            raise ProfileManagerError("UI preferences must be an object.")
        themes = {"light", "dark", "system"}
        columns = {"account", "environment", "last_opened"}
        theme = str(preferences.get("theme", "dark")).casefold()
        if theme == "system":
            theme = "dark"
        visible = preferences.get("visible_columns", sorted(columns))
        if theme not in themes or not isinstance(visible, list):
            raise ProfileManagerError("UI preferences contain an unsupported value.")
        normalized = {
            "theme": theme,
            "reduce_motion": bool(preferences.get("reduce_motion", False)),
            "visible_columns": [value for value in dict.fromkeys(map(str, visible)) if value in columns],
        }
        path = self.profile_service.paths.ui_preferences_json
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return normalized

    def get_about_info(self):
        """Return repository-derived, non-sensitive project metadata."""
        root = Path(self.profile_service.paths.project_root)

        def git(*arguments):
            try:
                result = subprocess.run(
                    ["git", *arguments], cwd=root, capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    timeout=2, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                return ""
            return result.stdout.strip() if result.returncode == 0 else ""

        remote = git("remote", "get-url", "origin")
        if remote.startswith("git@") and ":" in remote:
            host, path = remote[4:].split(":", 1)
            remote = f"https://{host}/{path}"
        if remote.endswith(".git"):
            remote = remote[:-4]
        # Avoid returning credentials if a developer has configured a remote
        # with embedded user-info.
        if "@" in remote.split("://")[-1].split("/")[0]:
            scheme, remainder = remote.split("://", 1)
            remote = f"{scheme}://{remainder.split('@', 1)[-1]}"
        developer_url = None
        try:
            metadata = json.loads(
                (root / "revamped" / "resources" / "about.json").read_text(
                    encoding="utf-8"
                )
            )
            candidate = None
            if isinstance(metadata, dict):
                candidate = metadata.get("developer_profile_url")
                if not candidate:
                    # Keep reading project metadata created by the earlier
                    # contributor-only About implementation.
                    candidate = metadata.get("contributor_github_url")
            if isinstance(candidate, str):
                candidate = candidate.strip()
                parsed = urlparse(candidate)
                if (
                    parsed.scheme == "https"
                    and parsed.hostname
                    and parsed.username is None
                    and parsed.password is None
                ):
                    developer_url = candidate
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            pass
        return _json_safe({
            "name": "Trình quản lý đa tài khoản Discord",
            "status": "Phiên bản phát triển — Pre-final",
            "commit": git("rev-parse", "--short", "HEAD") or "local",
            "branch": git("branch", "--show-current") or "không xác định",
            "repository": remote or None,
            "contributors": [CONTRIBUTOR_NAME],
            "developer_profile_url": developer_url,
            # Keep the old field available for any already-built frontend.
            "contributor_github_url": developer_url,
            "license": "LICENSE" if (root / "LICENSE").is_file() else "Chưa xác định",
            "stack": ["Python", "pywebview", "React", "Vite", "Tailwind CSS"],
        })

    def open_developer_profile(self):
        """Open the configured developer profile in the system default browser."""
        url = self.get_about_info().get("developer_profile_url")
        if not url:
            return {"opened": False, "configured": False}
        return {"opened": bool(webbrowser.open(url, new=2)), "configured": True}

    def open_contributor_github(self):
        """Compatibility alias for clients using the older About action."""
        return self.open_developer_profile()

    def set_optional_extension_policy(self, extension_name, enabled):
        if enabled is not True and enabled is not False:
            raise ProfileManagerError("Extension enablement must be true or false.")
        self.extension_service.set_extension_enabled(extension_name, enabled)
        return self.get_extension_policy()

    def shutdown(self):
        self.jobs.shutdown()


__all__ = ["JobManager", "ProductAPI", "ProxyDiagnostics"]
