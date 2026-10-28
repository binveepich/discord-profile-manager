"""Synthetic compatibility and safe product-mode account metadata."""

import json
import os
import re
import uuid

from .core import (
    PROFILE_OPEN_FOR_ACCOUNT_MESSAGE,
    ChromiumOpenError,
    InvalidAccountFormatError,
    ProfileManagerError,
    checked_path,
)
from .extensions import ExtensionService


ACCOUNT_MODE_DEVELOPMENT = "development"
ACCOUNT_MODE_PRODUCT = "product"

# Descriptive aliases keep callers readable while allowing older synthetic
# callers to use the terminology that existed before R13.
DEVELOPMENT_ACCOUNT_MODE = ACCOUNT_MODE_DEVELOPMENT
PRODUCT_ACCOUNT_MODE = ACCOUNT_MODE_PRODUCT
SYNTHETIC_ACCOUNT_MODE = ACCOUNT_MODE_DEVELOPMENT
INTERACTIVE_ACCOUNT_MODE = ACCOUNT_MODE_PRODUCT


def parse_account_string(account_string):
    """Parse the approved ``email:password[:totp]`` input format.

    The returned mapping is intentionally an internal-use value.  Callers may
    use it to stage the approved local Autofill configuration, but it must not
    be returned from a normal product DTO or written to the application
    catalog/logs.
    """
    if not isinstance(account_string, str):
        raise InvalidAccountFormatError(
            "Format must be email:password or email:password:2faSecret."
        )
    parts = account_string.strip().split(":")
    if len(parts) not in (2, 3):
        raise InvalidAccountFormatError(
            "Format must be email:password or email:password:2faSecret."
        )

    def clean(value):
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", "", value.strip())

    email = clean(parts[0])
    password = clean(parts[1])
    totp_secret = clean(parts[2]) if len(parts) == 3 else ""
    if not email or not password:
        raise InvalidAccountFormatError("Email and password cannot be empty.")
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise InvalidAccountFormatError("Enter a valid email address.")
    if any(ord(char) < 32 for char in email + password + totp_secret):
        raise InvalidAccountFormatError("Account input contains invalid characters.")
    if totp_secret:
        totp_secret = totp_secret.upper()
    return {
        "email": email,
        "password": password,
        "totp_secret": totp_secret,
    }


def parse_account_input(value):
    """Parse either the fast line format or the structured editor payload.

    Secrets remain transient: this helper returns them only to the explicit
    Autofill staging path and callers must never place the result in a DTO,
    catalog record, log, or export.
    """
    if isinstance(value, str):
        return parse_account_string(value)
    if not isinstance(value, dict):
        raise InvalidAccountFormatError(
            "Enter email:password[:2fa] or provide structured account fields."
        )
    email = value.get("email")
    password = value.get("password")
    totp_secret = value.get("totp_secret", value.get("totp", ""))
    if not isinstance(email, str) or not isinstance(password, str):
        raise InvalidAccountFormatError("Email and password cannot be empty.")
    if not isinstance(totp_secret, str):
        raise InvalidAccountFormatError("TOTP secret must be text when provided.")
    return parse_account_string(":".join((email, password, totp_secret)))


def derive_profile_name(email):
    """Derive the product default display name without exposing credentials."""
    if not isinstance(email, str):
        return "Profile"
    prefix = email.split("@", 1)[0].strip()
    prefix = re.sub(r"[<>:/\\|?*\x00-\x1f]", "", prefix).strip()
    return prefix[:120] or "Profile"


def normalize_account_mode(value):
    """Return the canonical account mode or reject an ambiguous mode."""
    if value is None:
        return ACCOUNT_MODE_DEVELOPMENT
    if not isinstance(value, str):
        raise ProfileManagerError("Account mode must be Development or Product.")
    normalized = value.strip().casefold().replace("_", "-").replace(" ", "-")
    if normalized in {"development", "dev", "safe", "synthetic", "synthetic-development"}:
        return ACCOUNT_MODE_DEVELOPMENT
    if normalized in {"product", "interactive", "interactive-product"}:
        return ACCOUNT_MODE_PRODUCT
    raise ProfileManagerError("Account mode must be Development or Product.")


class _NullLogger:
    def debug(self, *args, **kwargs):
        pass

    info = debug
    warning = debug
    error = debug


class AccountCompatibilityService:
    """Preserve synthetic config semantics and add safe product associations.

    Development mode intentionally retains the old ``email:password[:totp]``
    compatibility contract for disposable tests. Product mode has a separate
    input path and persists only non-sensitive account metadata. Secure
    credential storage is not implemented, so product mode does not accept or
    write passwords, authentication tokens, or TOTP secrets.
    """

    def __init__(
        self,
        paths,
        profile_service,
        extension_service=None,
        process_inspector=None,
        logger=None,
        *,
        account_mode=ACCOUNT_MODE_DEVELOPMENT,
        mode=None,
        allow_synthetic_credentials=True,
    ):
        self.paths = paths
        self.profile_service = profile_service
        self.extension_service = extension_service or ExtensionService(paths, profile_service, logger)
        self.process_inspector = process_inspector
        self.logger = logger or _NullLogger()
        self.account_mode = normalize_account_mode(
            account_mode if mode is None else mode
        )
        self.mode = self.account_mode
        self.allow_synthetic_credentials = bool(allow_synthetic_credentials)

    def _ensure_extension_installed(self, profile_id):
        return self.extension_service.ensure_profile_extension(profile_id)

    def _ensure_both_extensions_installed(self, profile_id):
        return self.extension_service.ensure_required_extensions(profile_id)

    def _get_config_path(self, profile_id, record=None):
        try:
            profile_dir = self.profile_service.require_profile_dir(
                profile_id, record=record
            )
        except TypeError:
            profile_dir = self.profile_service.require_profile_dir(profile_id)
        try:
            extension_dir = self.extension_service.profile_extension_path(
                profile_id, record=record
            )
        except TypeError:
            extension_dir = self.extension_service.profile_extension_path(profile_id)
        return checked_path(extension_dir / "config.js", profile_dir)

    def _read_local_account_config(self, profile_id):
        """Read the current local config without exposing its contents to logs."""
        config_file = self._get_config_path(profile_id)
        if not config_file.exists():
            return None
        try:
            return config_file.read_bytes()
        except (OSError, UnicodeError) as error:
            raise ProfileManagerError(
                "The existing local account configuration could not be read."
            ) from error

    def _stage_local_account_config(self, profile_id, original):
        """Stage a recoverable copy before a product/account transition."""
        if original is None:
            return None
        config_file = self._get_config_path(profile_id)
        backup = checked_path(
            config_file.with_name(f".account-config-{uuid.uuid4().hex}.bak"),
            config_file.parent,
        )
        try:
            with open(backup, "wb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
        except (OSError, UnicodeError) as error:
            if backup.exists():
                try:
                    backup.unlink()
                except OSError:
                    self.logger.warning("Temporary account backup could not be cleaned")
            raise ProfileManagerError(
                "The existing account configuration could not be staged safely."
            ) from error
        return backup

    def _restore_local_account_config(self, profile_id, original):
        """Restore the prior local config atomically after a failed transition."""
        config_file = self._get_config_path(profile_id)
        if original is None:
            if config_file.exists():
                config_file.unlink()
            return
        temp_file = checked_path(
            config_file.with_name(f".config-restore-{uuid.uuid4().hex}.tmp"),
            config_file.parent,
        )
        try:
            with open(temp_file, "wb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            temp_file.replace(config_file)
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    self.logger.warning("Temporary account restore could not be cleaned")

    @staticmethod
    def _discard_account_backup(backup, logger):
        if backup is not None and backup.exists():
            try:
                backup.unlink()
            except OSError:
                logger.warning("Temporary account backup could not be cleaned")

    def _is_running(self, profile_dir):
        if self.process_inspector is None:
            return False
        return self.process_inspector.using_directory(profile_dir)

    def _get_account_metadata(self, profile_id, record=None):
        getter = getattr(self.profile_service, "get_account_metadata", None)
        if not callable(getter):
            return None
        try:
            return getter(profile_id, record=record)
        except TypeError:
            return getter(profile_id)

    def _set_account_metadata(self, profile_id, metadata=None):
        setter = getattr(self.profile_service, "set_account_metadata", None)
        if not callable(setter):
            raise ProfileManagerError(
                "Product account associations require application-owned profile metadata."
            )
        return setter(profile_id, metadata)

    @staticmethod
    def _is_sensitive_field_name(value):
        normalized = str(value).casefold().replace("_", "").replace("-", "")
        return any(
            fragment in normalized
            for fragment in (
                "password", "token", "totp", "secret", "credential",
                "cookie", "session",
            )
        )

    @staticmethod
    def _clean_metadata_text(value, field, *, required=False, max_length=320):
        if value is None and not required:
            return ""
        if not isinstance(value, str):
            raise InvalidAccountFormatError(f"Product account {field} must be text.")
        value = value.strip()
        if required and not value:
            raise InvalidAccountFormatError(f"Product account {field} cannot be empty.")
        if len(value) > max_length or any(ord(char) < 32 for char in value):
            raise InvalidAccountFormatError(f"Product account {field} is invalid.")
        return value

    @classmethod
    def _normalize_product_metadata(cls, email_identifier, label=None):
        email = cls._clean_metadata_text(
            email_identifier, "email identifier", required=True, max_length=320
        )
        if ":" in email:
            raise InvalidAccountFormatError(
                "Product mode accepts an account identifier only; credential strings are unsupported."
            )
        label = cls._clean_metadata_text(label, "label", max_length=200)
        metadata = {"mode": ACCOUNT_MODE_PRODUCT, "email": email}
        if label:
            metadata["label"] = label
        return metadata

    def _product_account_from_metadata(self, profile_id, metadata):
        if not isinstance(metadata, dict):
            return None
        mode = metadata.get("mode")
        if mode == ACCOUNT_MODE_DEVELOPMENT:
            if self.account_mode != ACCOUNT_MODE_DEVELOPMENT:
                return None
            try:
                email = self._clean_metadata_text(
                    metadata.get("email"), "email identifier", required=True
                )
            except InvalidAccountFormatError:
                self.logger.warning(
                    "Ignoring invalid development account metadata for profile %s",
                    profile_id,
                )
                return None
            if not email.casefold().endswith("@example.invalid"):
                return None
            return {"mode": ACCOUNT_MODE_DEVELOPMENT, "email": email}
        if mode != ACCOUNT_MODE_PRODUCT:
            return None
        try:
            normalized = self._normalize_product_metadata(
                metadata.get("email"), metadata.get("label")
            )
        except InvalidAccountFormatError:
            self.logger.warning("Ignoring invalid product account metadata for profile %s", profile_id)
            return None
        # This return value contains identifiers only. It intentionally has no
        # password/token/TOTP-shaped fields for product-mode callers.
        return normalized

    def _enable_developer_mode(self, profile_id, *, check_running=True):
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        if check_running and self._is_running(profile_dir):
            raise ChromiumOpenError(PROFILE_OPEN_FOR_ACCOUNT_MESSAGE, profile_id=profile_id)
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
        """Set a mode-appropriate account without logging any supplied value."""
        if self.account_mode == ACCOUNT_MODE_PRODUCT:
            if isinstance(account_string, dict):
                if any(self._is_sensitive_field_name(key) for key in account_string):
                    raise InvalidAccountFormatError(
                        "Product mode does not support password, token, or TOTP persistence."
                    )
                if any(
                    key not in {"mode", "email", "email_identifier", "label", "account_label"}
                    for key in account_string
                ):
                    raise InvalidAccountFormatError(
                        "Product mode stores only an account label and email identifier."
                    )
                if account_string.get("mode", ACCOUNT_MODE_PRODUCT) != ACCOUNT_MODE_PRODUCT:
                    raise InvalidAccountFormatError("Product account mode must be product.")
                return self.set_product_account(
                    profile_id,
                    account_string.get("email", account_string.get("email_identifier")),
                    account_string.get("label", account_string.get("account_label")),
                )
            if not isinstance(account_string, str) or ":" in account_string:
                raise InvalidAccountFormatError(
                    "Product mode accepts an email/account identifier only. Passwords, tokens, and TOTP are unsupported."
                )
            return self.set_product_account(profile_id, account_string)

        if not self.allow_synthetic_credentials:
            if not isinstance(account_string, str) or ":" in account_string:
                raise InvalidAccountFormatError(
                    "Development mode refuses passwords, tokens, and TOTP values; "
                    "provide only a synthetic @example.invalid account identifier."
                )
            email = self._clean_metadata_text(
                account_string, "email identifier", required=True
            )
            if not email.casefold().endswith("@example.invalid"):
                raise InvalidAccountFormatError(
                    "Synthetic Development Mode accepts only an email ending in @example.invalid."
                )
            self._set_account_metadata(
                profile_id, {"mode": ACCOUNT_MODE_DEVELOPMENT, "email": email}
            )
            return self.get_account(profile_id)
        return self._set_synthetic_account(profile_id, account_string)

    def _set_synthetic_account(self, profile_id, account_string):
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
        if not email.casefold().endswith("@example.invalid"):
            raise InvalidAccountFormatError(
                "Synthetic Development Mode accepts only an email ending in @example.invalid."
            )
        if totp_secret:
            totp_secret = totp_secret.upper()
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        if self._is_running(profile_dir):
            raise ChromiumOpenError(PROFILE_OPEN_FOR_ACCOUNT_MESSAGE, profile_id=profile_id)
        original_config = self._read_local_account_config(profile_id)
        self._ensure_both_extensions_installed(profile_id)
        self._enable_developer_mode(profile_id, check_running=False)
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

        # Explicitly moving back to synthetic mode removes the safe product
        # association only after the local config is durably published.  If the
        # metadata write fails, restore the previous local configuration.
        if callable(getattr(self.profile_service, "set_account_metadata", None)):
            try:
                self._set_account_metadata(profile_id, None)
            except Exception:
                try:
                    self._restore_local_account_config(profile_id, original_config)
                except Exception as restore_error:
                    raise ProfileManagerError(
                        "Account mode change failed and the previous configuration could not be restored."
                    ) from restore_error
                raise

    def set_legacy_account(
        self, profile_id, account_string, *, parsed_account=None,
        extensions_ready=False, skip_running_check=False,
    ):
        """Stage one product account using the approved legacy Autofill flow.

        This explicit method is used only by the product API.  It keeps the
        R13 product metadata setter conservative for older callers while
        supporting the approved v1 behavior: an independent staged extension
        copy owns the plaintext ``config.js`` for each profile.
        """
        parsed = parsed_account or parse_account_input(account_string)
        if not isinstance(parsed, dict):
            raise InvalidAccountFormatError("Account input could not be parsed.")
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        if not skip_running_check and self._is_running(profile_dir):
            raise ChromiumOpenError(PROFILE_OPEN_FOR_ACCOUNT_MESSAGE, profile_id=profile_id)

        original_config = self._read_local_account_config(profile_id)
        if not extensions_ready:
            self._ensure_both_extensions_installed(profile_id)
        self._enable_developer_mode(profile_id, check_running=False)
        config_content = f"""// Discord Auto-fill Extension Configuration
const ACCOUNT = {{
    email: {json.dumps(parsed["email"], ensure_ascii=True)},
    password: {json.dumps(parsed["password"], ensure_ascii=True)},
    totpSecret: {json.dumps(parsed["totp_secret"], ensure_ascii=True)}
}};
"""
        config_file = self._get_config_path(profile_id)
        temp_file = checked_path(
            config_file.with_name(f".config-{uuid.uuid4().hex}.tmp"),
            config_file.parent,
        )
        try:
            with open(temp_file, "w", encoding="utf-8", newline="") as stream:
                stream.write(config_content)
                stream.flush()
                os.fsync(stream.fileno())
            temp_file.replace(config_file)
            try:
                self._set_account_metadata(
                    profile_id,
                    {"mode": ACCOUNT_MODE_PRODUCT, "email": parsed["email"]},
                )
            except Exception:
                self._restore_local_account_config(profile_id, original_config)
                raise
        except (OSError, UnicodeError) as error:
            try:
                self._restore_local_account_config(profile_id, original_config)
            except Exception as restore_error:
                raise ProfileManagerError(
                    "Account configuration failed and the previous configuration could not be restored."
                ) from restore_error
            raise ProfileManagerError(
                "Could not save the account configuration for this profile."
            ) from error
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    self.logger.warning("Temporary account configuration could not be cleaned")
        return self.get_account(profile_id)

    # Descriptive aliases used by product/API callers.
    set_product_legacy_account = set_legacy_account
    configure_autofill_account = set_legacy_account

    def set_product_account(self, profile_id, email_identifier=None, label=None, **metadata):
        """Persist only a product account label and non-secret identifier.

        Passwords, authentication tokens, TOTP secrets, and similar values are
        intentionally unsupported until secure Windows storage is implemented.
        This method neither deploys nor configures an extension.
        """
        if self.account_mode != ACCOUNT_MODE_PRODUCT:
            raise ProfileManagerError(
                "Select Interactive Product Mode before adding a product account."
            )
        if isinstance(email_identifier, dict):
            supplied = dict(email_identifier)
            if any(self._is_sensitive_field_name(key) for key in supplied):
                raise InvalidAccountFormatError(
                    "Product mode does not support password, token, or TOTP persistence."
                )
            supplied_mode = supplied.pop("mode", ACCOUNT_MODE_PRODUCT)
            if supplied_mode != ACCOUNT_MODE_PRODUCT:
                raise InvalidAccountFormatError("Product account mode must be product.")
            if label is None:
                label = supplied.pop("label", supplied.pop("account_label", None))
            email_identifier = supplied.pop(
                "email", supplied.pop("email_identifier", None)
            )
            metadata.update(supplied)
        if email_identifier is None:
            email_identifier = metadata.pop("email", metadata.pop("email_identifier", None))
        if label is None:
            label = metadata.pop("account_label", None)
        if any(self._is_sensitive_field_name(key) for key in metadata):
            raise InvalidAccountFormatError(
                "Product mode does not support password, token, or TOTP persistence."
            )
        if metadata:
            raise InvalidAccountFormatError(
                "Product mode stores only an account label and email identifier."
            )
        normalized = self._normalize_product_metadata(email_identifier, label)
        profile_dir = self.profile_service.require_profile_dir(profile_id)
        if self._is_running(profile_dir):
            raise ChromiumOpenError(PROFILE_OPEN_FOR_ACCOUNT_MESSAGE, profile_id=profile_id)

        # Stage the old local config first.  Clearing it before publication is
        # safe because a metadata failure restores the exact previous bytes.
        original_config = self._read_local_account_config(profile_id)
        backup = self._stage_local_account_config(profile_id, original_config)
        try:
            self._clear_local_account_config(profile_id)
            try:
                self._set_account_metadata(profile_id, normalized)
            except Exception:
                try:
                    self._restore_local_account_config(profile_id, original_config)
                except Exception as restore_error:
                    raise ProfileManagerError(
                        "Product account update failed and the previous configuration could not be restored."
                    ) from restore_error
                raise
        finally:
            self._discard_account_backup(backup, self.logger)
        return self.get_account(profile_id)

    def get_local_credentials(self, profile_id):
        """Read an existing profile-local credential config for explicit export.

        This intentionally does not inspect Chromium storage or extract a
        token.  It only parses fields already written by the Autofill config.
        """
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
                values[field] = json.loads(match.group(1))
            token = ""
            for field in ("discordToken", "token", "authorization"):
                match = re.search(rf"\b{field}\s*:\s*(\"(?:\\.|[^\"\\])*\")", content)
                if match:
                    token = json.loads(match.group(1))
                    break
            email = str(values["email"]).strip()
            password = str(values["password"]).strip()
            totp = str(values["totpSecret"]).strip()
            if not email or not password:
                return None
            result = {"email": email, "password": password, "totp_secret": totp}
            if token:
                result["discord_token"] = token
            return result
        except (OSError, UnicodeError, TypeError, ValueError):
            return None

    def get_account(self, profile_id, record=None):
        product = self._product_account_from_metadata(
            profile_id, self._get_account_metadata(profile_id, record=record)
        )
        if product is not None:
            return product
        # Product mode never interprets an old local synthetic config as a
        # product account. This prevents accidental exposure in the product UI
        # and keeps the storage boundary explicit.
        if self.account_mode == ACCOUNT_MODE_PRODUCT:
            return None
        config_file = self._get_config_path(profile_id, record=record)
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
            # Export may include a token only when a profile-local config
            # already stores one.  This reads existing data; it does not
            # extract authentication tokens from Chromium or Discord.
            for field in ("discordToken", "token", "authorization"):
                match = re.search(rf"\b{field}\s*:\s*(\"(?:\\.|[^\"\\])*\")", content)
                if match:
                    try:
                        values["discord_token"] = json.loads(match.group(1))
                    except (TypeError, ValueError):
                        values["discord_token"] = ""
                    break
            email = values["email"].strip()
            password = values["password"].strip()
            totp = values["totpSecret"].strip()
            if email and password:
                result = {"email": email, "password": password, "totp_secret": totp}
                if values.get("discord_token"):
                    result["discord_token"] = values["discord_token"]
                return result
        except (OSError, UnicodeError):
            self.logger.warning("Could not read autofill configuration for profile %s", profile_id)
        return None

    def _clear_local_account_config(self, profile_id):
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

    def remove_account(self, profile_id):
        """Remove account association/config only; never remove profile data."""
        original_config = self._read_local_account_config(profile_id)
        backup = self._stage_local_account_config(profile_id, original_config)
        try:
            self._clear_local_account_config(profile_id)
            if callable(getattr(self.profile_service, "set_account_metadata", None)):
                try:
                    self._set_account_metadata(profile_id, None)
                except Exception:
                    try:
                        self._restore_local_account_config(profile_id, original_config)
                    except Exception as restore_error:
                        raise ProfileManagerError(
                            "Account removal failed and the previous configuration could not be restored."
                        ) from restore_error
                    raise
        finally:
            self._discard_account_backup(backup, self.logger)

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
