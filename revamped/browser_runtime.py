"""Install, check, update, and roll back the bundled Ungoogled Chromium runtime.

The runtime folder is browser/ and holds only the Chromium build. An install or
update downloads the Windows x64 zip of one upstream release over HTTPS, checks
its size and the SHA-256 that GitHub publishes for it, extracts plain files into
a staging folder, confirms the chrome.exe version, and only then moves the
folder into place. Nothing from the archive is executed.

An update keeps the build it replaces as browser.previous, so the user can roll
back. Anything older than that is deleted. Every operation here touches only
browser/ and its sibling browser.* folders. It never writes to or deletes
profiles/, extensions/, logs/, or config/ (except this module's own
browser_runtime.json setting).
"""

import argparse
from datetime import datetime, timezone
import errno
import hashlib
import http.client
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import urllib.error
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

import psutil

from . import environment
from .chromium_version import PINNED_TAG
from .core import ProfileManagerError, ProjectPaths


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Source and update policy. The pinned build itself lives in chromium_version.py.
UPSTREAM_REPOSITORY = "ungoogled-software/ungoogled-chromium-windows"
# Updates are always started by the user. "latest" targets the newest upstream
# release, and "pinned" targets PINNED_TAG. First installs always use PINNED_TAG.
UPDATE_TARGET = "latest"
ASSET_NAME_TEMPLATE = "ungoogled-chromium_{tag}_windows_x64.zip"
API_BASE_URL = "https://api.github.com/repos/" + UPSTREAM_REPOSITORY
API_HOSTS = frozenset(("api.github.com",))
DOWNLOAD_HOSTS = frozenset(("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"))

API_TIMEOUT_SECONDS = 15
DOWNLOAD_TIMEOUT_SECONDS = 15
CHUNK_BYTES = 1024 * 1024
MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
RUNTIME_DIR_NAME = "browser"
STAGING_DIR_NAME = "browser.staging"    # the new build, extracted and checked before it moves in
PREVIOUS_DIR_NAME = "browser.previous"  # the build the last update replaced: the one rollback copy
OLDER_DIR_NAME = "browser.older"        # transient: the copy from before PREVIOUS during an update
ROLLBACK_DIR_NAME = "browser.rollback"  # transient: scratch name while a rollback swaps two builds
MARKER_FILE_NAME = "dpm-runtime.json"
SETTINGS_FILE_NAME = "browser_runtime.json"
USER_AGENT = "DiscordProfileManager-browser-runtime"

NETWORK_MESSAGE = "Không kết nối được tới GitHub. Kiểm tra mạng rồi thử lại."
INTERRUPTED_MESSAGE = "Tải Chromium bị gián đoạn, nên đã hủy. Bấm thử lại."
UNSAFE_ARCHIVE_MESSAGE = "Gói Chromium có đường dẫn hoặc liên kết không an toàn, nên đã hủy."
IN_USE_MESSAGE = (
    "Không thay được thư mục browser/, có thể vì Chromium đang dùng file trong đó. "
    "Đóng mọi cửa sổ Chromium rồi thử lại. browser/ không bị thay đổi."
)
CLOSE_CHROMIUM_MESSAGE = (
    "Hãy đóng mọi cửa sổ Chromium đang chạy từ browser/ rồi thử lại. browser/ không bị thay đổi."
)
RESTORE_FAILED_MESSAGE = (
    "Không hoàn tác được thao tác đổi bản Chromium. Hãy kiểm tra thư mục browser/ "
    "và browser.previous trước khi làm gì tiếp."
)
NO_PREVIOUS_MESSAGE = "Chưa có bản Chromium trước để quay lại. Bản trước chỉ có sau khi bạn cập nhật."
MANUAL_MESSAGE = (
    "Bạn có thể tự đặt Chromium: tải gói Windows x64 (.zip) của Ungoogled Chromium, "
    "giải nén, rồi đặt chrome.exe vào thư mục browser\\."
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_LOGGER = logging.getLogger("discord-profile-manager.browser-runtime")


class BrowserRuntimeError(ProfileManagerError):
    """A browser runtime problem. The message is safe to show to the user."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ignore_progress(stage, completed, total):
    return None


def _tag_version(tag):
    return str(tag).split("-", 1)[0]


def _parse_tag(tag):
    """Return a sortable (version, revision) key for a tag such as 152.0.7977.82-1.1."""
    version, _, revision = str(tag).partition("-")
    try:
        return (
            tuple(int(part) for part in version.split(".")),
            tuple(int(part) for part in (revision or "0").split(".")),
        )
    except ValueError as error:
        raise BrowserRuntimeError(f"Tên phiên bản Chromium không hợp lệ: {tag}") from error


def _require_https(url, hosts):
    parts = urlsplit(str(url))
    if parts.scheme != "https" or (parts.hostname or "") not in hosts:
        raise BrowserRuntimeError("Nguồn tải Chromium không hợp lệ, nên đã hủy.")


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Refuse a redirect that leaves HTTPS or the GitHub hosts this module uses."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_https(newurl, API_HOSTS | DOWNLOAD_HOSTS)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def load_auto_download(settings_path):
    """Return the auto-download switch. A missing or unreadable file means the default, on."""
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        _LOGGER.warning("browser_runtime.json is unreadable; using the default auto-download setting")
        return True
    value = data.get("auto_download") if isinstance(data, dict) else None
    return value if isinstance(value, bool) else True


def save_auto_download(settings_path, enabled):
    path = Path(settings_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps({"auto_download": bool(enabled)}, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _remove_tree(path):
    """Remove a folder this module created: a staging, older, or rollback copy only."""
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError as error:
        raise BrowserRuntimeError(
            "Không dọn được thư mục tạm của Chromium. Đóng các cửa sổ liên quan rồi thử lại."
        ) from error


def _remove_tree_quietly(path):
    try:
        _remove_tree(path)
    except BrowserRuntimeError:
        _LOGGER.warning("An older browser copy could not be removed; it is replaced on the next update")


def _remove_file(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        _LOGGER.warning("A temporary Chromium download could not be removed")


def _is_within(path, root):
    try:
        return Path(path).resolve().is_relative_to(root)
    except (OSError, ValueError):
        return False


def _runtime_process_ids(runtime_dir):
    """Return the PIDs of processes whose executable lies inside the runtime folder."""
    root = Path(runtime_dir).resolve()
    found = []
    for process in psutil.process_iter(["pid", "exe"]):
        exe = process.info.get("exe")
        if exe and _is_within(exe, root):
            found.append(process.info["pid"])
    return found


def _member_file_name(info):
    """Return a safe relative file name for a zip entry, or None for a folder entry."""
    if info.is_dir():
        return None
    if ((info.external_attr >> 16) & 0o170000) == 0o120000:  # symbolic link
        raise BrowserRuntimeError(UNSAFE_ARCHIVE_MESSAGE)
    name = info.filename.replace("\\", "/")
    parts = name.split("/")
    if name.startswith("/") or any(part in ("", "..") or ":" in part for part in parts):
        raise BrowserRuntimeError(UNSAFE_ARCHIVE_MESSAGE)
    return name


def _shared_top_folder(names):
    """Return "folder/" when every file sits under one top-level folder, otherwise ""."""
    if not names or not all("/" in name for name in names):
        return ""
    tops = {name.split("/", 1)[0] for name in names}
    return tops.pop() + "/" if len(tops) == 1 else ""


def _read_marker(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_marker(path, tag, asset):
    data = {
        "tag": tag,
        "asset": asset["name"],
        "sha256": asset["sha256"],
        "source": UPSTREAM_REPOSITORY,
        "installed_at": _now(),
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _restore_rename(source, target):
    try:
        os.rename(source, target)
    except OSError as error:
        raise BrowserRuntimeError(RESTORE_FAILED_MESSAGE) from error


def _exchange_folders(first, second, scratch):
    """Swap two sibling folders using renames only. A failed step puts both folders back."""
    os.rename(first, scratch)  # an OSError here changes nothing
    try:
        os.rename(second, first)
    except OSError:
        _restore_rename(scratch, first)
        raise
    try:
        os.rename(scratch, second)
    except OSError:
        _restore_rename(first, second)
        _restore_rename(scratch, first)
        raise


class BrowserRuntimeService:
    """Owns the browser/ runtime.

    The install, update, and rollback methods run synchronously. The product API
    starts them as background jobs through the shared JobManager, and the CLI
    calls them directly.
    """

    def __init__(self, paths, *, jobs=None, opener=None, version_reader=None,
                 process_ids=None, free_bytes=None, temp_dir=None):
        self.paths = paths
        self.runtime_dir = Path(paths.browser_exe).parent
        self.settings_path = Path(paths.config_dir) / SETTINGS_FILE_NAME
        self._jobs = jobs
        self._opener = opener or build_opener(_SafeRedirectHandler)
        self._version_reader = version_reader or environment.chromium_file_version
        self._process_ids = process_ids or _runtime_process_ids
        self._free_bytes = free_bytes or (lambda folder: shutil.disk_usage(folder).free)
        self._temp_dir = temp_dir
        self._lock = threading.RLock()
        self._job_id = None
        self._last_check = None

    # Reading state

    def installed(self):
        return self._describe(self.runtime_dir)

    def _describe(self, folder):
        """Version and tag of the chrome.exe in one runtime folder, read without launching it."""
        exe = folder / "chrome.exe"
        if not exe.is_file():
            return {"present": False, "tag": None, "version": None}
        version = self._version_reader(exe)
        marker = _read_marker(folder / MARKER_FILE_NAME)
        tag = None
        if marker and isinstance(marker.get("tag"), str) and version == _tag_version(marker["tag"]):
            tag = marker["tag"]
        return {"present": True, "tag": tag, "version": version}

    def _is_newer(self, candidate_tag, installed):
        if not installed["present"]:
            return False
        candidate = _parse_tag(candidate_tag)
        if installed["tag"]:
            return candidate > _parse_tag(installed["tag"])
        if installed["version"]:
            return candidate[0] > tuple(int(part) for part in installed["version"].split("."))
        return False

    def status(self):
        installed = self.installed()
        previous = self._describe(self.runtime_dir.with_name(PREVIOUS_DIR_NAME))
        return {
            "installed": installed["present"],
            "installed_version": installed["version"],
            "installed_tag": installed["tag"],
            "pinned_tag": PINNED_TAG,
            "update_target": UPDATE_TARGET,
            "auto_download": load_auto_download(self.settings_path),
            "previous": previous,
            "last_check": self._last_check,
            "job": self._current_job(),
        }

    def _current_job(self):
        if self._jobs is None or not self._job_id:
            return None
        try:
            job = self._jobs.get(self._job_id)
        except ProfileManagerError:
            return None
        return {
            "job_id": job["job_id"],
            "label": job["label"],
            "status": job["status"],
            "progress": job["progress"],
            "error": job["error"],
            "active": job["status"] in ("queued", "running"),
        }

    def active_job(self):
        job = self._current_job()
        return bool(job and job["active"])

    # Update check (network)

    def check_for_update(self):
        """Compare the installed build with GitHub's newest release. Never changes browser/."""
        installed = self.installed()
        result = {
            "checked_at": _now(),
            "error": None,
            "latest_tag": None,
            "update_target_tag": None,
            "update_available": False,
            "newer_upstream_available": False,
        }
        try:
            latest = self._latest_tag()
        except BrowserRuntimeError as error:
            result["error"] = str(error)
        else:
            target = PINNED_TAG if UPDATE_TARGET == "pinned" else latest
            result.update(
                latest_tag=latest,
                update_target_tag=target,
                update_available=self._is_newer(target, installed),
                newer_upstream_available=self._is_newer(latest, installed),
            )
        self._last_check = result
        return result

    def _latest_tag(self):
        release = self._api_json(f"{API_BASE_URL}/releases/latest")
        tag = release.get("tag_name") if isinstance(release, dict) else None
        if not isinstance(tag, str):
            raise BrowserRuntimeError("GitHub không trả về phiên bản mới nhất.")
        _parse_tag(tag)
        return tag

    def _release_asset(self, tag):
        release = self._api_json(f"{API_BASE_URL}/releases/tags/{tag}")
        name = ASSET_NAME_TEMPLATE.format(tag=tag)
        assets = release.get("assets", []) if isinstance(release, dict) else []
        match = next((item for item in assets if isinstance(item, dict) and item.get("name") == name), None)
        if match is None:
            raise BrowserRuntimeError(f"GitHub không có gói {name} cho phiên bản này.")
        # GitHub publishes a SHA-256 digest for every release asset. A match proves the
        # download is the file GitHub recorded. It does not defend against a compromised
        # GitHub, which is an accepted limit for this app.
        digest = str(match.get("digest") or "")
        sha256 = digest[len("sha256:"):] if digest.startswith("sha256:") else ""
        if not _SHA256_PATTERN.fullmatch(sha256):
            raise BrowserRuntimeError(
                "GitHub không công bố mã SHA-256 cho gói này, nên không tự cài được. " + MANUAL_MESSAGE
            )
        url = str(match.get("browser_download_url") or "")
        _require_https(url, DOWNLOAD_HOSTS)
        size = match.get("size")
        if not isinstance(size, int) or not 0 < size <= MAX_ARCHIVE_BYTES:
            raise BrowserRuntimeError("Kích thước gói Chromium trên GitHub không hợp lệ, nên đã hủy.")
        return {"name": name, "url": url, "size": size, "sha256": sha256}

    def _api_json(self, url):
        _require_https(url, API_HOSTS)
        request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
        try:
            with self._opener.open(request, timeout=API_TIMEOUT_SECONDS) as response:
                _require_https(response.geturl(), API_HOSTS)
                body = response.read(MAX_API_RESPONSE_BYTES + 1)
        except BrowserRuntimeError:
            raise
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise BrowserRuntimeError("GitHub không có phiên bản Chromium này.") from error
            if error.code in (403, 429):
                raise BrowserRuntimeError("GitHub đang giới hạn số yêu cầu. Thử lại sau ít phút.") from error
            raise BrowserRuntimeError(f"GitHub trả về lỗi {error.code}. Thử lại sau.") from error
        except (OSError, http.client.HTTPException) as error:
            raise BrowserRuntimeError(NETWORK_MESSAGE) from error
        if len(body) > MAX_API_RESPONSE_BYTES:
            raise BrowserRuntimeError("Phản hồi từ GitHub lớn bất thường, nên đã bỏ qua.")
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError as error:
            raise BrowserRuntimeError("Phản hồi từ GitHub không đọc được.") from error

    # Install, update, rollback

    def install(self, *, progress=None, cancel_event=None):
        """Install the pinned build. Refuses when browser/chrome.exe already exists."""
        return self._install(PINNED_TAG, update=False, progress=progress, cancel_event=cancel_event)

    def update(self, *, tag=None, progress=None, cancel_event=None):
        """Replace the installed build with the update target, or with an explicit tag."""
        if tag is None:
            tag = PINNED_TAG if UPDATE_TARGET == "pinned" else self._latest_tag()
        return self._install(tag, update=True, progress=progress, cancel_event=cancel_event)

    def rollback(self, *, progress=None, cancel_event=None):
        """Swap browser/ with browser.previous, the build kept by the last update. Renames only."""
        report = progress or _ignore_progress
        runtime = self._checked_runtime_dir()
        previous = runtime.with_name(PREVIOUS_DIR_NAME)
        scratch = runtime.with_name(ROLLBACK_DIR_NAME)
        if not (runtime / "chrome.exe").is_file():
            raise BrowserRuntimeError("Chưa có browser/chrome.exe để quay lại. Hãy tải Chromium trước.")
        if not (previous / "chrome.exe").is_file():
            raise BrowserRuntimeError(NO_PREVIOUS_MESSAGE)
        if self._process_ids(runtime):
            raise BrowserRuntimeError(CLOSE_CHROMIUM_MESSAGE)
        _remove_tree(scratch)
        report("installing", 0, 0)
        try:
            _exchange_folders(runtime, previous, scratch)
        except OSError as error:
            raise BrowserRuntimeError(IN_USE_MESSAGE) from error
        return {"version": self.installed()["version"], "path": f"{RUNTIME_DIR_NAME}/chrome.exe"}

    def _install(self, tag, *, update, progress, cancel_event):
        report = progress or _ignore_progress
        cancelled = cancel_event or threading.Event()
        _parse_tag(tag)
        runtime = self._checked_runtime_dir()
        staging = runtime.with_name(STAGING_DIR_NAME)
        previous = runtime.with_name(PREVIOUS_DIR_NAME)
        self._preflight(runtime, update)
        if update and self._process_ids(runtime):
            raise BrowserRuntimeError(CLOSE_CHROMIUM_MESSAGE)
        asset = self._release_asset(tag)
        self._check_free_space(asset["size"])
        archive = self._new_archive_path()
        try:
            self._download(asset, archive, report, cancelled)
            _remove_tree(staging)
            self._extract(archive, staging, report, cancelled)
            version = self._version_reader(staging / "chrome.exe")
            if version != _tag_version(tag):
                raise BrowserRuntimeError(
                    "Phiên bản Chromium trong gói không khớp với bản đã chọn, nên đã hủy. browser/ không bị thay đổi."
                )
            _write_marker(staging / MARKER_FILE_NAME, tag, asset)
            report("installing", 0, 0)
            self._swap(runtime, staging, previous, update)
        finally:
            _remove_file(archive)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return {"tag": tag, "version": version, "path": f"{RUNTIME_DIR_NAME}/chrome.exe"}

    def _checked_runtime_dir(self):
        runtime = self.runtime_dir
        if runtime.name != RUNTIME_DIR_NAME or runtime.parent != Path(self.paths.assets_root):
            raise BrowserRuntimeError("Đường dẫn browser/ không đúng, nên đã hủy.")
        return runtime

    def _preflight(self, runtime, update):
        exe = runtime / "chrome.exe"
        if update:
            if not exe.is_file():
                raise BrowserRuntimeError("Chưa có browser/chrome.exe để cập nhật. Hãy tải Chromium trước.")
            return
        if exe.is_file():
            raise BrowserRuntimeError("browser/chrome.exe đã có, nên không cần tải lại.")
        try:
            occupied = runtime.exists() and any(runtime.iterdir())
        except OSError as error:
            raise BrowserRuntimeError("Không đọc được thư mục browser/.") from error
        if occupied:
            raise BrowserRuntimeError(
                "browser/ đã có file nhưng thiếu chrome.exe. Ứng dụng không xóa file nào trong đó. "
                "Hãy chuyển thư mục này đi rồi thử lại."
            )

    def _check_free_space(self, archive_bytes):
        try:
            project_free = self._free_bytes(self.runtime_dir.parent)
            temp_free = self._free_bytes(self._temp_dir or tempfile.gettempdir())
        except OSError as error:
            raise BrowserRuntimeError("Không kiểm tra được dung lượng đĩa.") from error
        if project_free < archive_bytes * 3 or temp_free < archive_bytes + 64 * 1024 * 1024:
            raise BrowserRuntimeError(
                "Không đủ dung lượng đĩa để tải và giải nén Chromium. Hãy giải phóng dung lượng rồi thử lại."
            )

    def _new_archive_path(self):
        try:
            descriptor, name = tempfile.mkstemp(prefix="dpm-chromium-", suffix=".zip", dir=self._temp_dir)
        except OSError as error:
            raise BrowserRuntimeError("Không tạo được file tạm để tải Chromium.") from error
        os.close(descriptor)
        return Path(name)

    def _download(self, asset, destination, report, cancel_event):
        request = Request(asset["url"], headers={"User-Agent": USER_AGENT})
        digest = hashlib.sha256()
        written = 0
        try:
            with self._opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, destination.open("wb") as stream:
                _require_https(response.geturl(), DOWNLOAD_HOSTS)
                while True:
                    if cancel_event.is_set():
                        raise BrowserRuntimeError("Đã hủy tải Chromium.")
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > asset["size"]:
                        raise BrowserRuntimeError("Gói tải lớn hơn kích thước GitHub công bố, nên đã hủy.")
                    digest.update(chunk)
                    stream.write(chunk)
                    report("downloading", written, asset["size"])
        except BrowserRuntimeError:
            raise
        except urllib.error.HTTPError as error:
            raise BrowserRuntimeError(f"Không tải được gói từ GitHub (lỗi {error.code}).") from error
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise BrowserRuntimeError("Hết dung lượng đĩa khi tải Chromium.") from error
            raise BrowserRuntimeError(INTERRUPTED_MESSAGE) from error
        except http.client.HTTPException as error:
            raise BrowserRuntimeError(INTERRUPTED_MESSAGE) from error
        if written != asset["size"]:
            raise BrowserRuntimeError(INTERRUPTED_MESSAGE)
        if digest.hexdigest() != asset["sha256"]:
            raise BrowserRuntimeError(
                "Gói tải không khớp mã SHA-256 mà GitHub công bố, nên đã hủy. browser/ không bị thay đổi."
            )

    def _extract(self, archive_path, staging, report, cancel_event):
        """Extract plain files only. Nothing from the archive is executed."""
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = []
                total = 0
                for info in archive.infolist():
                    name = _member_file_name(info)
                    if name is not None:
                        members.append((info, name))
                        total += info.file_size
                if total > MAX_EXTRACTED_BYTES:
                    raise BrowserRuntimeError("Gói Chromium giải nén quá lớn, nên đã hủy.")
                prefix = _shared_top_folder([name for _, name in members])
                staging.mkdir(parents=True)
                root = staging.resolve()
                written = 0
                for info, name in members:
                    relative = name[len(prefix):]
                    if not relative:
                        continue
                    target = staging.joinpath(*relative.split("/"))
                    if not _is_within(target, root):
                        raise BrowserRuntimeError(UNSAFE_ARCHIVE_MESSAGE)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as sink:
                        while True:
                            if cancel_event.is_set():
                                raise BrowserRuntimeError("Đã hủy giải nén Chromium.")
                            block = source.read(CHUNK_BYTES)
                            if not block:
                                break
                            sink.write(block)
                            written += len(block)
                            report("extracting", written, total)
        except BrowserRuntimeError:
            raise
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise BrowserRuntimeError("Hết dung lượng đĩa khi giải nén Chromium.") from error
            raise BrowserRuntimeError("Không giải nén được gói Chromium, nên đã hủy.") from error
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, ValueError) as error:
            raise BrowserRuntimeError("Gói tải không phải file zip Chromium hợp lệ, nên đã hủy.") from error
        if not (staging / "chrome.exe").is_file():
            raise BrowserRuntimeError("Gói tải không có chrome.exe, nên đã hủy.")

    def _swap(self, runtime, staging, previous, update):
        """Move the staged build into browser/.

        An update keeps the build it replaces as browser.previous and deletes the copy
        that was kept before it. Every step is a rename, so a failure can be undone
        without copying anything.
        """
        if not update:
            # Fresh install: browser/ is missing or empty. A leftover browser.previous is left alone.
            had_runtime = runtime.exists()
            if had_runtime:
                try:
                    os.rmdir(runtime)
                except OSError as error:
                    raise BrowserRuntimeError(
                        "Thư mục browser/ không trống nên chưa thể cài. browser/ không bị thay đổi."
                    ) from error
            try:
                os.rename(staging, runtime)
            except OSError as error:
                if had_runtime:
                    runtime.mkdir(exist_ok=True)
                raise BrowserRuntimeError(
                    "Không đặt được Chromium mới vào browser/. Thư mục browser/ không bị thay đổi."
                ) from error
            return
        older = runtime.with_name(OLDER_DIR_NAME)
        _remove_tree(older)  # a leftover from an earlier attempt
        had_previous = previous.exists()
        if had_previous:
            try:
                os.rename(previous, older)  # step 1: park the copy from before the last update
            except OSError as error:
                raise BrowserRuntimeError(IN_USE_MESSAGE) from error
        try:
            os.rename(runtime, previous)  # step 2: the current build becomes the rollback copy
        except OSError as error:
            if had_previous:
                _restore_rename(older, previous)
            raise BrowserRuntimeError(IN_USE_MESSAGE) from error
        try:
            os.rename(staging, runtime)  # step 3: the new build takes browser/
        except OSError as error:
            _restore_rename(previous, runtime)
            if had_previous:
                _restore_rename(older, previous)
            raise BrowserRuntimeError(
                "Không đặt được Chromium mới vào browser/. Bản cũ vẫn được giữ nguyên."
            ) from error
        if had_previous:
            _remove_tree_quietly(older)  # success: nothing older than the new rollback copy is kept

    # Background jobs

    def start_install(self):
        return self._start_job("Cài đặt Chromium", self.install)

    def start_update(self):
        return self._start_job("Cập nhật Chromium", self.update)

    def start_rollback(self):
        return self._start_job("Quay về bản Chromium trước", self.rollback)

    def cancel(self):
        if self._jobs is None or not self._job_id:
            return False
        self._jobs.cancel(self._job_id)
        return True

    def _start_job(self, label, action):
        if self._jobs is None:
            raise BrowserRuntimeError("Không có bộ quản lý tác vụ nền.")
        with self._lock:
            if self.active_job():
                raise BrowserRuntimeError("Đang có tác vụ Chromium chạy. Đợi xong rồi thử lại.")
            job_id = self._jobs.start(
                label,
                lambda cancel_event, progress: self._run_action(action, cancel_event, progress),
                initial_progress={"stage": "queued", "completed": 0, "total": 0},
            )
            self._job_id = job_id
        return job_id

    @staticmethod
    def _run_action(action, cancel_event, progress):
        def report(stage, completed, total):
            progress({"stage": stage, "completed": int(completed), "total": int(total)})

        try:
            return action(progress=report, cancel_event=cancel_event)
        except BrowserRuntimeError:
            if cancel_event.is_set():
                return {"cancelled": True}
            raise

    def start_on_startup(self):
        """Start the first install, or a background update check. Never blocks and never raises."""
        try:
            if not load_auto_download(self.settings_path):
                return None
            if not self.installed()["present"]:
                return self.start_install()
            if self._jobs is not None:
                self._jobs.start("Kiểm tra cập nhật Chromium", lambda cancel_event, progress: self.check_for_update())
        except (BrowserRuntimeError, ProfileManagerError) as error:
            _LOGGER.warning("Browser runtime startup step skipped: %s", error)
        return None

    def set_auto_download(self, enabled):
        save_auto_download(self.settings_path, enabled)
        return self.status()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage the bundled Ungoogled Chromium runtime in browser/.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show the installed build and the kept copy (no network, no browser launch)")
    commands.add_parser("check", help="ask GitHub for the newest release (network)")
    commands.add_parser("install", help="install the pinned build when browser/chrome.exe is missing (network)")
    commands.add_parser("update", help="replace the installed build with the update target (network)")
    commands.add_parser("rollback", help="swap back to the build kept by the last update (no network)")
    switch = commands.add_parser("auto-download", help="turn automatic download and update checks on or off")
    switch.add_argument("state", choices=("on", "off"))
    args = parser.parse_args(argv)

    service = BrowserRuntimeService(ProjectPaths(PROJECT_ROOT, assets_root=PROJECT_ROOT))
    try:
        if args.command == "status":
            result = service.status()
        elif args.command == "check":
            result = service.check_for_update()
        elif args.command == "auto-download":
            result = service.set_auto_download(args.state == "on")
        else:
            result = _run_with_progress(service, args.command)
    except BrowserRuntimeError as error:
        print(f"Lỗi: {error}", flush=True)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


def _run_with_progress(service, command):
    last_step = [-1]

    def report(stage, completed, total):
        if total and completed * 10 // total != last_step[0]:
            last_step[0] = completed * 10 // total
            print(f"{stage}: {last_step[0] * 10}%", flush=True)

    actions = {"install": service.install, "update": service.update, "rollback": service.rollback}
    return actions[command](progress=report)


if __name__ == "__main__":
    raise SystemExit(main())
