"""Import legacy portable Chromium profiles into the revamped profile manager.

Run from the repository root. The default mode is a dry run and writes nothing.

    python -B scripts/import_legacy_profiles.py --root <STATE_ROOT> --source <LEGACY_INSTALL>
    python -B scripts/import_legacy_profiles.py --root <STATE_ROOT> --source <LEGACY_INSTALL> --apply

--root    The revamped state root: the folder that holds config\\, profiles\\ and data\\.
--source  A legacy portable install: the folder that holds data\\Local State, for example
          H:\\OLD FFA Discord\\ungoogled-chromium-portable. Repeat --source to import more
          than one install. The first listed install wins when one account appears in several.

Each legacy profile folder is copied as-is into profiles\\profile_NNNN\\ and registered
through ProfileService.batch_operation(), so the catalog is published once at the end.
The account email becomes product metadata. Passwords, TOTP secrets and tokens stay inside
the copied config.js; this script never prints, logs or reports them. The source is read only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from revamped.core import (  # noqa: E402
    ProfileManagerError,
    checked_path,
    ensure_tree_has_no_links,
    validate_profile_id,
)
from revamped.main import compose_product_candidate  # noqa: E402
from revamped.models import new_profile_record, timestamp_from_epoch, utc_timestamp  # noqa: E402
from revamped.product_api import ProductAPI  # noqa: E402
from revamped.profiles import MAX_DISPLAYED_PROFILES  # noqa: E402


LEDGER_NAME = "legacy_import_ledger.json"
DISK_MARGIN_BYTES = 1024 ** 3
FLAT_CHROMIUM_MARKERS = (
    "Cookies", "Network", "Local Storage", "IndexedDB", "Login Data", "History",
    "Bookmarks", "Sessions", "Session Storage", "Web Data", "Service Worker",
)
# Regenerable Chromium caches. --skip-caches omits only these, at the profile root
# and inside Default\. Cookies, storage, IndexedDB and preferences are always kept.
CACHE_DIR_NAMES = frozenset({
    "Cache", "Code Cache", "GPUCache", "ShaderCache", "GrShaderCache",
    "DawnCache", "DawnWebGPUCache", "DawnGraphiteCache", "GraphiteDawnCache", "Media Cache",
})
AUTOFILL_CONFIG = Path("Unpacked Extensions") / "discord-autofill-extension" / "config.js"
TOKEN_EXTRACTOR_DIR = Path("Unpacked Extensions") / "discord-token-extractor-extension"
# The legacy writer does not escape values, so the pattern is deliberately simple.
ACCOUNT_FIELD = re.compile(r'\b(email|password|totpSecret)\s*:\s*"((?:\\.|[^"\\])*)"')


class SourceError(Exception):
    """A legacy install cannot be read at all."""


@dataclass(frozen=True)
class Skip:
    source: str
    legacy_id: str
    reason: str


@dataclass(frozen=True)
class Candidate:
    source: str
    legacy_id: str
    folder: Path
    name: str
    created_at: str | None
    email: str | None
    has_password: bool
    has_totp: bool
    account_note: str | None
    token_extractor: bool
    full_totals: tuple[int, int]
    no_cache_totals: tuple[int, int]

    def copy_totals(self, skip_caches):
        return self.no_cache_totals if skip_caches else self.full_totals


def natural_key(value):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]


def is_usable_email(value):
    return (
        isinstance(value, str)
        and 3 <= len(value) <= 320
        and value.count("@") == 1
        and not value.startswith("@")
        and not value.endswith("@")
        and ":" not in value
        and not any(char.isspace() or ord(char) < 32 for char in value)
    )


def mask_email(value):
    if not value:
        return "(none)"
    local, _, domain = value.rpartition("@")
    return f"{local[:1]}***@{domain}"


def email_digest(value):
    return hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:16]


def gib(value):
    return f"{value / 1024 ** 3:.2f}"


def mib(value):
    return f"{value / 1024 ** 2:.1f}"


def tree_totals(folder, skip_caches):
    """Return (file count, byte total) that a copy of ``folder`` would produce."""
    root = os.path.normcase(os.path.abspath(folder))
    default = os.path.normcase(os.path.join(root, "Default"))
    files = total = 0
    for current, dirnames, filenames in os.walk(folder):
        here = os.path.normcase(os.path.abspath(current))
        if skip_caches and here in (root, default):
            dirnames[:] = [name for name in dirnames if name not in CACHE_DIR_NAMES]
        for name in filenames:
            files += 1
            try:
                total += os.path.getsize(os.path.join(current, name))
            except OSError:
                pass
    return files, total


def copy_ignore(folder, skip_caches):
    root = os.path.normcase(os.path.abspath(folder))
    default = os.path.normcase(os.path.join(root, "Default"))

    def ignore(directory, names):
        if not skip_caches:
            return []
        here = os.path.normcase(os.path.abspath(directory))
        if here in (root, default):
            return [name for name in names if name in CACHE_DIR_NAMES]
        return []

    return ignore


def read_account(config_file):
    """Return (email, has_password, has_totp, note). Only the email is ever returned."""
    try:
        text = config_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, False, False, "config.js could not be read; imported without an account"
    fields = {}
    for match in ACCOUNT_FIELD.finditer(text):
        fields.setdefault(match.group(1), match.group(2))
    has_password = bool(fields.get("password"))
    has_totp = bool(fields.get("totpSecret"))
    raw_email = fields.get("email", "")
    if not raw_email:
        return None, has_password, has_totp, "config.js has no email field; imported without an account"
    email = raw_email
    if "\\" in raw_email:
        try:
            email = json.loads(f'"{raw_email}"')
        except ValueError:
            return None, has_password, has_totp, "email field could not be decoded; imported without an account"
    email = email.strip()
    if not is_usable_email(email):
        return None, has_password, has_totp, "email field is not a usable identifier; imported without an account"
    return email, has_password, has_totp, None


def inspect_folder(source, legacy_id, folder, info, busy, orphan):
    """Return a Candidate or a Skip. Each check mirrors a rule the revamped app enforces."""

    def skip(reason):
        return Skip(source, legacy_id, reason)

    if not folder.exists():
        return skip("registry entry has no folder")
    if not folder.is_dir():
        return skip("path is not a folder")
    if str(folder.resolve()).casefold() in busy:
        return skip("Chromium is running on this profile; close it first")
    try:
        ensure_tree_has_no_links(folder)
    except ProfileManagerError:
        return skip("contains links or junctions; not copied")
    if not ((folder / "Preferences").is_file() or (folder / "Default" / "Preferences").is_file()):
        return skip("no Chromium Preferences file; not a browser profile")
    if any((folder / marker).exists() for marker in FLAT_CHROMIUM_MARKERS):
        return skip("browser data sits in the profile root (shared-root layout); the app refuses to open it")
    local_state = folder / "Local State"
    if local_state.is_file():
        try:
            last_used = json.loads(local_state.read_text(encoding="utf-8-sig")).get("profile", {}).get("last_used", "Default")
            last_used = validate_profile_id(last_used)
            if last_used != "Default" and not (folder / last_used).is_dir():
                return skip("Chromium last_used folder is missing; the app would refuse to open it")
        except (OSError, ValueError, TypeError, AttributeError, ProfileManagerError):
            return skip("per-profile Local State is unreadable or invalid")

    name = info.get("name") if isinstance(info.get("name"), str) else ""
    name = name.strip() or legacy_id
    created = info.get("created")
    created_at = None
    if isinstance(created, int) and not isinstance(created, bool) and created > 0:
        created_at = timestamp_from_epoch(created)

    account_dir = folder / "Unpacked Extensions"
    config_files = []
    if account_dir.is_dir():
        preferred = folder / AUTOFILL_CONFIG
        config_files = [preferred] if preferred.is_file() else sorted(account_dir.rglob("config.js"))
    email = None
    has_password = has_totp = False
    account_note = None
    if config_files:
        email, has_password, has_totp, account_note = read_account(config_files[0])
    else:
        account_note = "no autofill config.js; imported without an account"

    return Candidate(
        source=source,
        legacy_id=legacy_id,
        folder=folder,
        name=name,
        created_at=created_at,
        email=email,
        has_password=has_password,
        has_totp=has_totp,
        account_note=account_note,
        token_extractor=(folder / TOKEN_EXTRACTOR_DIR).is_dir(),
        full_totals=tree_totals(folder, False),
        no_cache_totals=tree_totals(folder, True),
    )


def discover(install, include_orphans, busy):
    source = install.parent.name or install.name
    data = install / "data"
    registry_file = data / "Local State"
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8-sig"))
        cache = registry["profile"]["info_cache"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SourceError(f"{install}: data\\Local State is missing or has an unexpected shape") from error
    if not isinstance(cache, dict):
        raise SourceError(f"{install}: profile.info_cache is not an object")
    folders = {path.name: path for path in data.iterdir() if path.is_dir() and path.name.startswith("Profile ")}

    candidates, skips = [], []
    for legacy_id in sorted(cache, key=natural_key):
        info = cache[legacy_id] if isinstance(cache[legacy_id], dict) else {}
        result = inspect_folder(source, legacy_id, data / legacy_id, info, busy, orphan=False)
        (candidates if isinstance(result, Candidate) else skips).append(result)
    orphan_ids = sorted(set(folders) - set(cache), key=natural_key)
    for legacy_id in orphan_ids:
        if not include_orphans:
            skips.append(Skip(source, legacy_id, "orphan folder: not in the legacy registry (use --include-orphans to import it)"))
            continue
        result = inspect_folder(source, legacy_id, folders[legacy_id], {}, busy, orphan=True)
        (candidates if isinstance(result, Candidate) else skips).append(result)
    summary = {"source": source, "path": str(install), "registry_entries": len(cache),
               "folders": len(folders), "orphan_folders": len(orphan_ids)}
    return candidates, skips, summary


def build_plan(candidates, skips, existing_emails, ledger_pairs, ledger_digests, limit):
    planned = []
    seen_accounts = {}
    for candidate in candidates:
        if (candidate.source, candidate.legacy_id) in ledger_pairs:
            skips.append(Skip(candidate.source, candidate.legacy_id, "already imported (legacy import ledger)"))
            continue
        digest = email_digest(candidate.email) if candidate.email else None
        if digest and digest in ledger_digests:
            skips.append(Skip(candidate.source, candidate.legacy_id, "account already imported from a legacy profile (ledger)"))
            continue
        key = candidate.email.casefold() if candidate.email else None
        if key and key in existing_emails:
            skips.append(Skip(candidate.source, candidate.legacy_id, "account already in the revamped catalog (duplicate)"))
            continue
        if key and key in seen_accounts:
            skips.append(Skip(candidate.source, candidate.legacy_id,
                              f"same account as {seen_accounts[key]} (first listed install wins)"))
            continue
        if key:
            seen_accounts[key] = f"{candidate.source}/{candidate.legacy_id}"
        planned.append(candidate)
    if limit is not None and len(planned) > limit:
        for candidate in planned[limit:]:
            skips.append(Skip(candidate.source, candidate.legacy_id, "not selected: beyond --limit"))
        planned = planned[:limit]
    return planned


def planned_profile_ids(service, count):
    records = service.get_profile_metadata()
    first = service.next_profile_id({record["profile_id"]: record for record in records})
    start = int(first.rsplit("_", 1)[1])
    return [f"profile_{start + index:04d}" for index in range(count)]


def read_ledger(root):
    path = root / "config" / LEDGER_NAME
    if not path.exists():
        return {"version": 1, "imports": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("imports"), list):
            raise ValueError("unexpected ledger shape")
        return data
    except (OSError, ValueError) as error:
        raise SystemExit(f"{path} is unreadable. Fix or move it before importing; nothing was changed.") from error


def write_ledger(root, entries):
    data = read_ledger(root)
    data["imports"].extend(entries)
    target = root / "config" / LEDGER_NAME
    temp = target.with_name(f".{LEDGER_NAME}.{uuid.uuid4().hex}.tmp")
    with open(temp, "w", encoding="utf-8", newline="") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, target)


def snapshot_metadata(root, target):
    """Copy the small metadata files so a rollback can restore them exactly."""
    target.mkdir(parents=True, exist_ok=True)
    for relative in ("config/profiles.json", "config/legacy_import_ledger.json",
                     "config/ui_preferences.json", "data/Local State", "legacy/data/Local State"):
        source = root / relative
        if source.is_file():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def quarantine(path, profiles_dir, stamp):
    """Move a partial copy out of discovery's way. Nothing is deleted."""
    target = profiles_dir / f".import-partial-{path.name}-{stamp}"
    try:
        path.rename(target)
        return str(target)
    except OSError:
        return None


def apply_plan(composition, planned, skip_caches, stamp):
    service = composition.profile_service
    paths = composition.paths
    profiles_dir = paths.profiles_dir
    created, errors, registered_dirs = [], [], []
    try:
        with service.batch_operation() as catalog:
            for candidate in planned:
                owned = None
                record = None
                try:
                    profile_id = service.next_profile_id({r["profile_id"]: r for r in catalog["profiles"]})
                    destination = checked_path(profiles_dir / profile_id, profiles_dir)
                    if destination.exists():
                        raise ProfileManagerError(f"{profile_id} already exists; no folder was overwritten")
                    profiles_dir.mkdir(parents=True, exist_ok=True)
                    ensure_tree_has_no_links(candidate.folder)
                    owned = destination
                    shutil.copytree(
                        candidate.folder, destination,
                        ignore=copy_ignore(candidate.folder, skip_caches),
                        copy_function=shutil.copy2,
                    )
                    if tree_totals(destination, False) != candidate.copy_totals(skip_caches):
                        raise ProfileManagerError("the copy does not match the source size and file count")
                    created_at = candidate.created_at or utc_timestamp()
                    record = new_profile_record(
                        profile_id, candidate.name, destination, paths, created_at=created_at
                    ).to_mapping()
                    record["updated_at"] = created_at
                    catalog["profiles"].append(record)
                    service.set_account_metadata(
                        profile_id,
                        {"mode": "product", "email": candidate.email} if candidate.email else None,
                    )
                except Exception as error:
                    if record is not None and record in catalog["profiles"]:
                        catalog["profiles"].remove(record)
                    moved = quarantine(owned, profiles_dir, stamp) if owned is not None and owned.exists() else None
                    errors.append({
                        "source": candidate.source,
                        "legacy_profile": candidate.legacy_id,
                        "error": str(error)[:200],
                        "partial_copy_moved_to": moved,
                    })
                    continue
                registered_dirs.append(destination)
                created.append({
                    "source": candidate.source,
                    "legacy_profile": candidate.legacy_id,
                    "profile_id": profile_id,
                    "account": mask_email(candidate.email) if candidate.email else None,
                    "email": candidate.email,
                    "account_sha256_16": email_digest(candidate.email) if candidate.email else None,
                    "copy_files": tree_totals(destination, False)[0],
                })
    except Exception as error:
        # The publish failed: nothing from this run is registered. Move the copies aside.
        for destination in registered_dirs:
            quarantine(destination, profiles_dir, stamp)
        errors.append({"stage": "publish", "error": str(error)[:200]})
        return [], errors, False
    return created, errors, True


def verify(root, expected, expected_total):
    composition = compose_product_candidate(root)
    service = composition.profile_service
    records = {record["profile_id"]: record for record in service.get_profile_metadata()}
    problems = []
    for profile_id, email in expected:
        record = records.get(profile_id)
        if record is None:
            problems.append(f"{profile_id}: missing from the catalog")
            continue
        try:
            service.require_profile_dir(profile_id)
            service.get_browser_profile_dir(profile_id)
        except ProfileManagerError:
            problems.append(f"{profile_id}: the app cannot resolve this profile layout")
            continue
        stored = ((record.get("account") or {}).get("email") or "")
        if stored.casefold() != (email or "").casefold():
            problems.append(f"{profile_id}: account metadata does not match")
    api = ProductAPI(composition)
    try:
        listed = len(api.list_profiles())
    finally:
        api.shutdown()
    if len(records) != expected_total:
        problems.append(f"catalog holds {len(records)} profiles, expected {expected_total}")
    if listed != expected_total:
        problems.append(f"the app lists {listed} profiles, expected {expected_total}")
    return {"catalog_count": len(records), "listed_by_app": listed,
            "expected": expected_total, "problems": problems}


def overlaps(first, second):
    first, second = first.resolve(), second.resolve()
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def busy_set(inspector, folders):
    if not folders:
        return set()
    return {str(Path(path).resolve()).casefold() for path in inspector.using_directories(list(folders))}


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", required=True, help="revamped state root (contains config\\ profiles\\ data\\)")
    parser.add_argument("--source", action="append", required=True, help="legacy portable install folder; repeatable")
    parser.add_argument("--apply", action="store_true", help="write the import (default is a dry run)")
    parser.add_argument("--skip-caches", action="store_true", help="omit regenerable Chromium caches to save disk space")
    parser.add_argument("--include-orphans", action="store_true", help="also import folders missing from the legacy registry")
    parser.add_argument("--limit", type=int, default=None, help="import only the first N eligible profiles")
    parser.add_argument("--report", type=Path, default=None, help="write a JSON report here (apply always writes one)")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be zero or greater")
    return args


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.root).absolute()
    installs = [Path(source).absolute() for source in args.source]
    if not (root / "config" / "profiles.json").is_file():
        raise SystemExit(
            f"{root} is not an initialized revamped state root (config\\profiles.json is missing). "
            "Start the revamped app once against this root, or choose the correct root. Nothing was changed."
        )
    for install in installs:
        if not (install / "data" / "Local State").is_file():
            raise SystemExit(f"{install} is not a legacy install (data\\Local State is missing). Nothing was changed.")
        if overlaps(install, root):
            raise SystemExit("A legacy source and the state root must not contain each other. Nothing was changed.")

    composition = compose_product_candidate(root)
    service = composition.profile_service
    inspector = composition.process_inspector
    records = service.get_profile_metadata()
    existing_emails = set()
    for record in records:
        account = record.get("account") or {}
        if isinstance(account.get("email"), str) and account["email"].strip():
            existing_emails.add(account["email"].strip().casefold())
    ledger = read_ledger(root)
    ledger_pairs = {(entry.get("source"), entry.get("legacy_profile")) for entry in ledger["imports"]}
    ledger_digests = {entry.get("account_sha256_16") for entry in ledger["imports"] if entry.get("account_sha256_16")}

    folders = [path for install in installs for path in (install / "data").iterdir()
               if path.is_dir() and path.name.startswith("Profile ")]
    try:
        busy = busy_set(inspector, folders)
    except Exception as error:
        raise SystemExit("Cannot check whether Chromium is using the legacy profiles; refusing to continue.") from error

    candidates, skips, source_summaries = [], [], []
    for install in installs:
        try:
            found, missed, summary = discover(install, args.include_orphans, busy)
        except SourceError as error:
            raise SystemExit(f"{error}. Nothing was changed.") from error
        candidates.extend(found)
        skips.extend(missed)
        source_summaries.append(summary)

    planned = build_plan(candidates, skips, existing_emails, ledger_pairs, ledger_digests, args.limit)
    predicted = planned_profile_ids(service, len(planned))

    need = sum(candidate.copy_totals(args.skip_caches)[1] for candidate in planned)
    free = shutil.disk_usage(root).free
    blockers = []
    if need + DISK_MARGIN_BYTES > free:
        blockers.append(
            f"disk space: the copy needs {gib(need)} GiB plus a 1 GiB margin, but {root.drive} has "
            f"{gib(free)} GiB free. Use --skip-caches, free space, or choose another --root."
        )
    if len(records) + len(planned) > MAX_DISPLAYED_PROFILES:
        blockers.append(f"the app supports at most {MAX_DISPLAYED_PROFILES} profiles")
    try:
        if inspector.using_directories([composition.paths.data_dir, composition.paths.profiles_dir], exact=True):
            blockers.append("Chromium is using the revamped data or profiles root. Close the revamped app's browser windows first.")
    except Exception:
        blockers.append("cannot check whether Chromium is using the revamped roots")

    skip_counts = {}
    for item in skips:
        skip_counts[item.reason] = skip_counts.get(item.reason, 0) + 1

    mode = "apply" if args.apply else "dry-run"
    print(f"Mode: {mode}")
    print(f"State root: {root}")
    for summary in source_summaries:
        print(f"Source [{summary['source']}]: registry entries={summary['registry_entries']} "
              f"folders={summary['folders']} orphan folders={summary['orphan_folders']}")
    print(f"Revamped profiles before import: {len(records)}")
    print(f"Options: skip_caches={args.skip_caches} include_orphans={args.include_orphans} limit={args.limit}")
    print(f"Planned to import: {len(planned)}  (copy {gib(need)} GiB, free on {root.drive} {gib(free)} GiB)")
    print(f"Skipped: {len(skips)}")
    print("")
    print("Planned copies (legacy -> revamped id, masked account, copy size, credential flags):")
    for index, candidate in enumerate(planned):
        if index >= 200:
            print(f"  ... {len(planned) - index} more (see the report)")
            break
        flags = f"password={'yes' if candidate.has_password else 'no'} totp={'yes' if candidate.has_totp else 'no'}"
        extractor = " token-extractor=present" if candidate.token_extractor else ""
        print(f"  [{candidate.source}] {candidate.legacy_id} -> {predicted[index]}  "
              f"account={mask_email(candidate.email)}  copy={mib(candidate.copy_totals(args.skip_caches)[1])} MiB  "
              f"{flags}{extractor}")
    print("")
    print("Skipped profiles (reason):")
    not_selected = 0
    for item in skips:
        if item.reason.startswith("not selected"):
            not_selected += 1
            continue
        print(f"  [{item.source}] {item.legacy_id}: {item.reason}")
    if not_selected:
        print(f"  {not_selected} eligible profiles not selected by --limit (listed in the report)")
    if skip_counts:
        print("")
        print("Skip counts by reason:")
        for reason, count in sorted(skip_counts.items(), key=lambda pair: -pair[1]):
            print(f"  {count:4d}  {reason}")
    if blockers:
        print("")
        print("BLOCKERS (no writes will happen):")
        for blocker in blockers:
            print(f"  - {blocker}")

    report = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "state_root": str(root),
        "options": {"skip_caches": args.skip_caches, "include_orphans": args.include_orphans, "limit": args.limit},
        "sources": source_summaries,
        "profiles_before": len(records),
        "planned_count": len(planned),
        "planned": [
            {
                "source": c.source,
                "legacy_profile": c.legacy_id,
                "predicted_profile_id": predicted[index],
                "account": mask_email(c.email) if c.email else None,
                "credentials_in_config_js": {"password": c.has_password, "totp": c.has_totp},
                "token_extractor_present": c.token_extractor,
                "copy_mib": round(c.copy_totals(args.skip_caches)[1] / 1024 ** 2, 1),
                "copy_files": c.copy_totals(args.skip_caches)[0],
                "note": c.account_note,
            }
            for index, c in enumerate(planned)
        ],
        "skipped": [{"source": s.source, "legacy_profile": s.legacy_id, "reason": s.reason} for s in skips],
        "skip_counts": skip_counts,
        "disk": {"copy_bytes": need, "free_bytes": free},
        "blockers": blockers,
    }

    if not args.apply:
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"Report written: {args.report}")
        print("")
        print("DRY RUN: nothing was written. Re-run with --apply to import.")
        return 2 if blockers else 0

    if blockers:
        print("")
        print("Refusing to apply because of the blockers above. Nothing was written.")
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = root / "logs" / "legacy-import" / stamp
    snapshot_metadata(root, run_dir / "before")
    created, errors, published = apply_plan(composition, planned, args.skip_caches, stamp)
    if published and created:
        write_ledger(root, [
            {
                "source": item["source"],
                "legacy_profile": item["legacy_profile"],
                "profile_id": item["profile_id"],
                "account_sha256_16": item["account_sha256_16"],
                "skip_caches": args.skip_caches,
                "imported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
            for item in created
        ])
    expected = [(item["profile_id"], item["email"]) for item in created]
    verification = verify(root, expected, len(records) + len(created)) if published else None

    report["mode"] = "apply"
    report["apply"] = {
        "published": published,
        "created_count": len(created),
        "created": [{key: value for key, value in item.items() if key != "email"} for item in created],
        "errors": errors,
        "run_dir": str(run_dir),
    }
    report["verification"] = verification
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("")
    print(f"Created: {len(created)}   Errors: {len(errors)}   Published: {published}")
    for item in created:
        print(f"  [{item['source']}] {item['legacy_profile']} -> {item['profile_id']}  account={item['account']}")
    for error in errors:
        print(f"  ERROR {error}")
    if verification is not None:
        print(f"Verification: catalog={verification['catalog_count']} listed_by_app={verification['listed_by_app']} "
              f"expected={verification['expected']}")
        for problem in verification["problems"]:
            print(f"  PROBLEM {problem}")
    print(f"Report: {run_dir / 'report.json'}")
    ok = published and not errors and verification is not None and not verification["problems"]
    return 0 if ok or (published and not errors and not created) else 3


if __name__ == "__main__":
    raise SystemExit(main())
