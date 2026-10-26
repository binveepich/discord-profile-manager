#!/usr/bin/env python3
"""Build a sanitized beta release from committed Git content only."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable


VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TOKEN_RE = re.compile(r"[\w-]{24,}\.[\w-]{6}\.[\w-]{27,}")
ASSIGNMENT_RE = re.compile(
    r"(?i)\b[\w-]*(?:password|passwd|totp|secret)[\w-]*\b\s*(?:=|:)\s*(['\"])(.*?)\1"
)
PROXY_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[a-zA-Z][\w+.-]*://)?"
    r"[^/\s:@'\"`(){}<>]+:[^/\s@'\"`(){}<>]+@"
    r"(?:\[[^\]\s]+\]|[a-zA-Z0-9.-]+)(?::\d+)?"
    r"(?=$|[\s'\"`(){}<>;,])"
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s\"'<>|]*")
ACCOUNT_ASSIGNMENT_RE = re.compile(
    r"(?im)\b(?:user\w*|email\w*|account\w*|password|passwd|totp\w*|secret\w*|token\w*|discord[_-]?\w*)\b"
    r"\s*[:=]\s*(['\"])(.*?)\1"
)
class ExportError(Exception):
    """An expected validation or export failure."""


def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ExportError(detail or f"git {' '.join(args)} failed")
    return result


def resolve_ref(root: Path, ref: str) -> str:
    result = run_git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}", check=False)
    commit = result.stdout.decode("ascii", errors="ignore").strip()
    if result.returncode or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        raise ExportError(f"Git ref does not resolve to a commit: {ref}")
    return commit


def archive_files(root: Path, commit: str) -> dict[str, bytes]:
    result = run_git(root, "archive", "--format=tar", commit)
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=__import__("io").BytesIO(result.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                name = member.name.replace("\\", "/")
                while name.startswith("./"):
                    name = name[2:]
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise ExportError(f"Unsafe path in Git archive: {name}")
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ExportError(f"Unsupported non-file Git archive member: {name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ExportError(f"Could not read Git archive member: {name}")
                files[name] = stream.read()
    except tarfile.TarError as exc:
        raise ExportError(f"Could not read Git archive: {exc}") from exc
    return files


def _glob_match(path: str, pattern: str) -> bool:
    path = path.casefold()
    pattern = pattern.casefold()
    if pattern.startswith("**/"):
        pattern = pattern[3:]
        parts = path.split("/")
        candidates = ["/".join(parts[index:]) for index in range(len(parts))]
        candidates.append(parts[-1])
        return any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates)
    if pattern.endswith("/**"):
        base = pattern[:-3].rstrip("/")
        return path == base or path.startswith(base + "/")
    if "/" not in pattern:
        return fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], pattern)
    return fnmatch.fnmatchcase(path, pattern)


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(_glob_match(path, pattern) for pattern in patterns)


def load_manifest(script_path: Path) -> dict:
    manifest_path = script_path.with_name("release_manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"Could not load release manifest: {manifest_path}") from exc
    if manifest.get("version") != 1 or not manifest.get("allowlist"):
        raise ExportError("Release manifest is missing its version 1 allowlist")
    return manifest


def legacy_imports(files: dict[str, bytes], selected: set[str]) -> tuple[set[str], list[str]]:
    imported: set[str] = set()
    for path in sorted(selected):
        if not path.startswith("revamped/") or not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(files[path].decode("utf-8"), filename=path)
        except (UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names if alias.name == "legacy" or alias.name.startswith("legacy."))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module == "legacy" or node.module.startswith("legacy."):
                    imported.add(node.module)
                    imported.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*")

    legacy_paths: set[str] = set()
    for module in sorted(imported):
        parts = module.split(".")
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            for candidate in (prefix + ".py", prefix + "/__init__.py"):
                if candidate in files:
                    legacy_paths.add(candidate)
    return legacy_paths, sorted(imported)


def selected_paths(files: dict[str, bytes], manifest: dict) -> tuple[set[str], list[str]]:
    allowlist = manifest["allowlist"]
    selected = {path for path in files if matches_any(path, allowlist)}
    legacy_paths, imports = legacy_imports(files, selected)
    if manifest.get("legacy_imports") == "include-imported-modules-only":
        selected.update(legacy_paths)
    return selected, imports


def read_text(data: bytes) -> str | None:
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError:
            return None


def scan_contents(files: dict[str, bytes], paths: Iterable[str]) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    failures: list[tuple[str, int, str]] = []
    warnings: list[tuple[str, int, str]] = []
    for path in sorted(paths):
        text = read_text(files[path])
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern, label in (
                (TOKEN_RE, "Discord token"),
            ):
                if pattern.search(line):
                    failures.append((path, line_number, label))
            if any(match.group(2).strip() for match in ASSIGNMENT_RE.finditer(line)):
                failures.append((path, line_number, "credential assignment"))
            if any(not is_proxy_placeholder(match.group(0)) for match in PROXY_RE.finditer(line)):
                failures.append((path, line_number, "proxy credentials"))
            for pattern, label in ((EMAIL_RE, "email address"), (WINDOWS_PATH_RE, "absolute Windows path")):
                if pattern.search(line):
                    warnings.append((path, line_number, label))
    return failures, warnings


def is_proxy_placeholder(value: str) -> bool:
    """Ignore literal UI examples while still rejecting populated proxy URLs."""
    lowered = value.casefold()
    return any(
        marker in lowered
        for marker in ("user:pass@host", "username:password@host", "host:port", "example.com")
    )


def check_autofill_template(files: dict[str, bytes], paths: set[str]) -> str | None:
    config_path = "extensions/discord-autofill-extension/config.js"
    if not any(path.startswith("extensions/discord-autofill-extension/") for path in paths):
        return None
    if config_path not in paths:
        return "missing from the ref's release files"
    text = read_text(files[config_path])
    if text is None:
        return "not readable as a text template"
    email_match = EMAIL_RE.search(text)
    if email_match:
        line = text.count("\n", 0, email_match.start()) + 1
        return f"contains an email address at line {line}"
    for match in ACCOUNT_ASSIGNMENT_RE.finditer(text):
        if match.group(2).strip():
            return f"non-empty {match.group(0).split(':', 1)[0].split('=', 1)[0].strip()} field at line {text.count(chr(10), 0, match.start()) + 1}"
    return None


def check_runtime_blockers(files: dict[str, bytes], paths: set[str]) -> list[str]:
    """Ensure hard-required built-in extensions are present in the export."""
    source_path = "revamped/extensions.py"
    if source_path not in paths:
        return []
    try:
        tree = ast.parse(files[source_path].decode("utf-8"), filename=source_path)
    except (UnicodeDecodeError, SyntaxError):
        return [f"Could not inspect required extension wiring in {source_path}"]
    string_constants: dict[str, str] = {}
    required_value: ast.AST | None = None
    for node in tree.body:
        value = None
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        for target in targets:
            if isinstance(target, ast.Name) and isinstance(value, ast.Constant) and isinstance(value.value, str):
                string_constants[target.id] = value.value
            if isinstance(target, ast.Name) and target.id == "REQUIRED_EXTENSION_NAMES":
                required_value = value
    required_names: list[str] = []
    if isinstance(required_value, (ast.Tuple, ast.List)):
        for item in required_value.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                required_names.append(item.value)
            elif isinstance(item, ast.Name) and item.id in string_constants:
                required_names.append(string_constants[item.id])
    missing = [
        name for name in required_names
        if not any(path.startswith(f"extensions/{name}/") for path in paths)
    ]
    if missing:
        return [
            f"{source_path} requires extensions/{name}/, which is absent from the release allowlist"
            for name in missing
        ]
    return []


def validate_selected(files: dict[str, bytes], paths: set[str], manifest: dict):
    protected_patterns = [
        *manifest.get("denylist", []),
        *manifest.get("source_only_optional", []),
    ]
    denied = sorted(path for path in paths if matches_any(path, protected_patterns))
    failures, warnings = scan_contents(files, paths)
    template_issue = check_autofill_template(files, paths)
    runtime_blockers = check_runtime_blockers(files, paths)
    if template_issue:
        failures.append(("extensions/discord-autofill-extension/config.js", 0, f"autofill config is not an empty template: {template_issue}"))
    return denied, failures, warnings, template_issue, runtime_blockers


def is_text_candidate(path: str, data: bytes) -> bool:
    return read_text(data) is not None


def print_report(
    ref: str,
    commit: str,
    files: dict[str, bytes],
    selected: set[str],
    manifest: dict,
    imported: list[str],
    denied: list[str],
    failures: list[tuple[str, int, str]],
    warnings: list[tuple[str, int, str]],
    template_issue: str | None,
    runtime_blockers: list[str],
    generated_files: set[str] | None = None,
) -> None:
    generated_files = generated_files or set()
    all_paths = set(files)
    excluded = sorted(all_paths - selected)
    text_candidates = sum(1 for path in selected if is_text_candidate(path, files[path]))
    print(f"Ref: {ref}")
    print(f"Commit: {commit}")
    print(f"Legacy imports: {', '.join(imported) if imported else 'none; legacy/ omitted'}")
    for pattern in manifest.get("source_only_optional", []):
        print(f"Retained in repository; excluded from release: {pattern}")
    print(f"Included source files: {len(selected)} ({text_candidates} text files)")
    print(f"Excluded archived files: {len(excluded)}")
    print("Would include:")
    for path in sorted(selected):
        print(f"  {path}")
    if generated_files:
        for path in sorted(generated_files):
            print(f"  {path} (fresh frontend build)")
    elif any(pattern == "frontend/dist/**" for pattern in manifest.get("generated", [])):
        print("  frontend/dist/** (fresh build; file count known after npm build)")
    print("Excluded archived paths:")
    for path in excluded:
        print(f"  {path}")
    print(f"Hard denylist hits: {len(denied)}")
    for path in denied:
        print(f"  {path}")
    print(f"Content scan failures: {len(failures)}")
    for path, line, label in failures:
        line_text = f":{line}" if line else ""
        print(f"  {path}{line_text}: {label}; matched value [REDACTED]")
    print(f"Content scan warnings: {len(warnings)}")
    for path, line, label in warnings:
        print(f"  {path}:{line}: {label}; matched value [REDACTED]")
    if template_issue is None:
        print("Autofill config.js empty-template check: PASS")
    else:
        print(f"Autofill config.js empty-template check: FAIL ({template_issue})")
    print(f"Runtime blockers: {len(runtime_blockers)}")
    for blocker in runtime_blockers:
        print(f"  {blocker}")


def npm_executable() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def build_frontend(files: dict[str, bytes], selected: set[str]) -> dict[str, bytes]:
    frontend_files = [path for path in selected if path.startswith("frontend/")]
    if not any(path.endswith("/package-lock.json") for path in frontend_files):
        raise ExportError("frontend/package-lock.json is required for npm ci")
    with tempfile.TemporaryDirectory(prefix="dpm-release-frontend-") as temp_name:
        frontend_root = Path(temp_name) / "frontend"
        frontend_root.mkdir()
        for path in frontend_files:
            relative = PurePosixPath(path).relative_to("frontend")
            target = frontend_root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(files[path])
        for command in ([npm_executable(), "ci"], [npm_executable(), "run", "build"]):
            print(f"Running in temporary frontend copy: {' '.join(command)}")
            try:
                result = subprocess.run(command, cwd=frontend_root, check=False)
            except OSError as exc:
                raise ExportError(f"Could not run {command[0]}: {exc}") from exc
            if result.returncode:
                raise ExportError(f"Frontend command failed with exit code {result.returncode}: {' '.join(command)}")
        dist_root = frontend_root / "dist"
        if not dist_root.is_dir():
            raise ExportError("Frontend build succeeded but did not create frontend/dist/")
        built = {
            "frontend/dist/" + path.relative_to(dist_root).as_posix(): path.read_bytes()
            for path in dist_root.rglob("*")
            if path.is_file()
        }
        if not built:
            raise ExportError("Frontend build created an empty frontend/dist/")
        return built


def write_release(root: Path, version: str, ref: str, commit: str, files: dict[str, bytes]) -> tuple[Path, Path]:
    build_root = root / "build"
    output_name = f"discord-profile-manager-{version}"
    output_dir = build_root / output_name
    zip_path = build_root / f"{output_name}.zip"
    if output_dir.exists() or zip_path.exists():
        raise ExportError(f"Refusing to overwrite existing release output: {output_dir} or {zip_path}")
    build_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [f"ref: {ref}", f"commit: {commit}", f"date: {timestamp}", "", "SHA-256  path"]
    for path in sorted(files):
        lines.append(f"{hashlib.sha256(files[path]).hexdigest()}  {path}")
    payload = dict(files)
    payload["RELEASE_MANIFEST.txt"] = ("\n".join(lines) + "\n").encode("utf-8")

    with tempfile.TemporaryDirectory(prefix=".dpm-export-", dir=build_root) as temp_name:
        temp_root = Path(temp_name)
        temp_payload = temp_root / output_name
        temp_payload.mkdir()
        for name, data in payload.items():
            target = temp_payload.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        temp_zip = temp_root / f"{output_name}.zip"
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(payload):
                archive.write(temp_payload.joinpath(*PurePosixPath(path).parts), f"{output_name}/{path}")
        os.replace(temp_payload, output_dir)
        os.replace(temp_zip, zip_path)
    return output_dir, zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a sanitized release from a committed Git ref")
    parser.add_argument("--ref", required=True, help="Git ref to export; contents come from git archive")
    parser.add_argument("--version", required=True, help="Release folder/zip version label")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report without building or writing")
    args = parser.parse_args(argv)
    if not VERSION_RE.fullmatch(args.version) or args.version in {".", ".."}:
        print("ERROR: version may contain only letters, numbers, dots, underscores, and hyphens", file=sys.stderr)
        return 2

    try:
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
        if root_result.returncode:
            raise ExportError("Run this command from inside a Git working tree")
        root = Path(root_result.stdout.decode("utf-8", errors="replace").strip())
        script_path = Path(__file__).resolve()
        manifest = load_manifest(script_path)
        commit = resolve_ref(root, args.ref)
        archived = archive_files(root, commit)
        selected, imported = selected_paths(archived, manifest)
        denied, failures, warnings, template_issue, runtime_blockers = validate_selected(archived, selected, manifest)
        print_report(args.ref, commit, archived, selected, manifest, imported, denied, failures, warnings,
                     template_issue, runtime_blockers)
        if denied or failures or runtime_blockers:
            print("Export validation failed; no output was written.", file=sys.stderr)
            return 1
        if args.dry_run:
            print("Dry run complete; frontend build and output writing were skipped.")
            return 0

        # Refuse existing output before doing the potentially lengthy frontend build.
        output_name = f"discord-profile-manager-{args.version}"
        if (root / "build" / output_name).exists() or (root / "build" / f"{output_name}.zip").exists():
            raise ExportError(f"Refusing to overwrite existing release version: {args.version}")
        built = build_frontend(archived, selected)
        release_files = {path: archived[path] for path in selected}
        release_files.update(built)
        final_denied, final_failures, final_warnings, final_template_issue, final_runtime_blockers = validate_selected(
            release_files, set(release_files), manifest
        )
        if final_denied or final_failures or final_runtime_blockers:
            print_report(args.ref, commit, release_files, set(release_files), manifest, imported,
                         final_denied, final_failures, final_warnings, final_template_issue,
                         final_runtime_blockers, set(built))
            raise ExportError("Post-build release validation failed; no output was written")
        output_dir, zip_path = write_release(root, args.version, args.ref, commit, release_files)
        print(f"Release folder: {output_dir}")
        print(f"Release zip: {zip_path}")
        return 0
    except ExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
