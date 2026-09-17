"""Isolated compatibility boundary for the legacy account workflow."""

import json
import os
import re
import uuid

from .core import InvalidAccountFormatError, ProfileManagerError, checked_path
from .extensions import ExtensionService


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    info = debug
    warning = debug
    error = debug


class AccountCompatibilityService:
    """Preserve legacy account/config semantics without redesigning storage."""

    def __init__(self, paths, profile_service, extension_service=None, process_inspector=None, logger=None):
        self.paths = paths
        self.profile_service = profile_service
        self.extension_service = extension_service or ExtensionService(paths, profile_service, logger)
        self.process_inspector = process_inspector
        self.logger = logger or _NullLogger()

    def _ensure_extension_installed(self, profile_id):
        return self.extension_service.ensure_profile_extension(profile_id)

    def _ensure_both_extensions_installed(self, profile_id):
        return self.extension_service.ensure_required_extensions(profile_id)

    def _get_config_path(self, profile_id):
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        extension_dir = self.extension_service.profile_extension_path(profile_id)
        return checked_path(extension_dir / "config.js", profile_dir)

    def _is_running(self, profile_dir):
        if self.process_inspector is None:
            return False
        return self.process_inspector.using_directory(profile_dir)

    def _enable_developer_mode(self, profile_id):
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        if self._is_running(profile_dir):
            raise ProfileManagerError(
                "Close this profile's Chromium windows before configuring its account."
            )
        prefs_file = self.profile_service.get_browser_profile_dir(profile_id) / "Preferences"
        if not prefs_file.exists():
            self.logger.warning("Preferences not found for profile %s", profile_id)
            return
        try:
            prefs = json.loads(prefs_file.read_text(encoding="utf-8"))
            if "extensions" not in prefs:
                prefs["extensions"] = {}
            prefs["extensions"].setdefault("ui", {})["developer_mode"] = True
            temp_file = checked_path(prefs_file.with_suffix(".tmp"), profile_dir)
            with open(temp_file, "w", encoding="utf-8") as stream:
                json.dump(prefs, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temp_file.replace(prefs_file)
        except Exception as error:
            raise ProfileManagerError("Cannot enable developer mode.") from error

    def set_account(self, profile_id, account_string):
        """Accept legacy email:password[:totp] and write one local config."""
        if not isinstance(account_string, str):
            raise InvalidAccountFormatError("Format must be email:password or email:password:2faSecret")

        def normalize(text):
            if not text:
                return ""
            return re.sub(r"\s+", "", text.strip())

        parts = account_string.strip().split(":")
        if len(parts) < 2:
            raise InvalidAccountFormatError("Format must be email:password or email:password:2faSecret")
        email = normalize(parts[0])
        password = normalize(parts[1])
        totp_secret = normalize(parts[2]) if len(parts) > 2 else ""
        if not email or not password:
            raise InvalidAccountFormatError("Email and password cannot be empty")
        if totp_secret:
            totp_secret = totp_secret.upper()
        self._ensure_both_extensions_installed(profile_id)
        self._enable_developer_mode(profile_id)
        config_content = f"""// Discord Auto-fill Extension Configuration
const ACCOUNT = {{
    email: {json.dumps(email, ensure_ascii=True)},
    password: {json.dumps(password, ensure_ascii=True)},
    totpSecret: {json.dumps(totp_secret, ensure_ascii=True)}
}};
"""
        config_file = self._get_config_path(profile_id)
        temp_file = checked_path(
            config_file.with_name(f".config-{uuid.uuid4().hex}.tmp"), config_file.parent
        )
        try:
            with open(temp_file, "w", encoding="utf-8", newline="") as stream:
                stream.write(config_content)
                stream.flush()
                os.fsync(stream.fileno())
            temp_file.replace(config_file)
        except (OSError, UnicodeError) as error:
            raise ProfileManagerError(
                f"Could not save the account configuration for profile {profile_id}."
            ) from error
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    self.logger.warning("Temporary account configuration could not be cleaned")

    def get_account(self, profile_id):
        config_file = self._get_config_path(profile_id)
        if not config_file.exists():
            return None
        try:
            content = config_file.read_text(encoding="utf-8")
            values = {}
            for field in ("email", "password", "totpSecret"):
                match = re.search(rf"\b{field}\s*:\s*(\"(?:\\.|[^\"\\])*\")", content)
                if not match:
                    return None
                try:
                    values[field] = json.loads(match.group(1))
                except (TypeError, ValueError):
                    return None
            email = values["email"].strip()
            password = values["password"].strip()
            totp = values["totpSecret"].strip()
            if email and password:
                return {"email": email, "password": password, "totp_secret": totp}
        except (OSError, UnicodeError):
            self.logger.warning("Could not read autofill configuration for profile %s", profile_id)
        return None

    def remove_account(self, profile_id):
        config_file = self._get_config_path(profile_id)
        if not config_file.exists():
            return
        empty_config = """// Discord Auto-fill Extension Configuration
const ACCOUNT = {
    email: "",
    password: "",
    totpSecret: ""
};
"""
        temp_file = checked_path(
            config_file.with_name(f".config-{uuid.uuid4().hex}.tmp"), config_file.parent
        )
        try:
            with open(temp_file, "w", encoding="utf-8", newline="") as stream:
                stream.write(empty_config)
                stream.flush()
                os.fsync(stream.fileno())
            temp_file.replace(config_file)
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    self.logger.warning("Temporary account configuration could not be cleaned")

    @staticmethod
    def mask_email(email):
        if not email or "@" not in email:
            return "***"
        name, domain = email.split("@", 1)
        masked = "*" * len(name) if len(name) <= 2 else name[:2] + "*" * (len(name) - 2)
        return f"{masked}@{domain}"

    @staticmethod
    def mask_password(password):
        return "Not set" if not password else "•" * max(len(password), 8)

    @staticmethod
    def mask_totp(totp):
        return "Not set" if not totp else "•" * max(len(totp), 6)
