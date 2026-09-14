"""Development-only composition for the parallel implementation.

The stable application entrypoint is still the repository-root ``main.py``.
This module deliberately requires an explicit disposable workspace before it
constructs stateful services.
"""

from dataclasses import dataclass
import argparse
import logging
from pathlib import Path

from .accounts import AccountCompatibilityService
from .core import ProfileManagerError, ProjectPaths
from .extensions import ExtensionService
from .gui import ProfileGUIController
from .launcher import ChromiumLauncher
from .processes import ChromiumProcessInspector
from .profiles import ProfileService
from .storage import LegacyStateStore, ProfileCatalogStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISPOSABLE_ROOT = PROJECT_ROOT / "tmp"


@dataclass(frozen=True)
class RevampedComposition:
    """Explicitly wired development services."""

    paths: ProjectPaths
    logger: logging.Logger
    catalog_store: ProfileCatalogStore
    legacy_store: LegacyStateStore
    process_inspector: ChromiumProcessInspector
    profile_service: ProfileService
    extension_service: ExtensionService
    account_service: AccountCompatibilityService
    launcher: ChromiumLauncher
    controller: ProfileGUIController


def _safe_workspace_root(value):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ProfileManagerError(
            "revamped.main requires --workspace-root under the repository tmp directory."
        )
    DISPOSABLE_ROOT.mkdir(parents=True, exist_ok=True)
    candidate = Path(value).absolute().resolve()
    disposable_root = DISPOSABLE_ROOT.absolute().resolve()
    if candidate == disposable_root or not candidate.is_relative_to(disposable_root):
        raise ProfileManagerError(
            "revamped.main accepts only a disposable workspace below repository tmp/."
        )
    return candidate


def compose(workspace_root, *, process_inspector=None, process_factory=None, logger=None):
    """Build the complete dependency graph below an approved disposable root."""
    root = _safe_workspace_root(workspace_root)
    paths = ProjectPaths(root)
    log = logger or logging.getLogger("revamped")
    inspector = process_inspector or ChromiumProcessInspector()
    catalog_store = ProfileCatalogStore(paths, log)
    legacy_store = LegacyStateStore(paths, log)
    profile_service = ProfileService(
        paths,
        catalog_store=catalog_store,
        legacy_store=legacy_store,
        process_inspector=inspector,
        logger=log,
    )
    extension_service = ExtensionService(paths, profile_service, log)
    account_service = AccountCompatibilityService(
        paths,
        profile_service,
        extension_service,
        process_inspector=inspector,
        logger=log,
    )
    launcher = ChromiumLauncher(
        paths,
        profile_service,
        process_inspector=inspector,
        process_factory=process_factory,
        logger=log,
    )
    controller = ProfileGUIController(
        profile_service,
        account_service,
        launcher,
        extension_service,
        process_inspector=inspector,
        logger=log,
    )
    return RevampedComposition(
        paths=paths,
        logger=log,
        catalog_store=catalog_store,
        legacy_store=legacy_store,
        process_inspector=inspector,
        profile_service=profile_service,
        extension_service=extension_service,
        account_service=account_service,
        launcher=launcher,
        controller=controller,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Disposable-workspace revamped development composition")
    parser.add_argument(
        "--workspace-root",
        help="required disposable state root below repository tmp/",
    )
    args = parser.parse_args(argv)
    if args.workspace_root is None:
        raise SystemExit(
            "revamped.main is not ready yet; no stateful development operation was run. "
            "Provide --workspace-root below tmp/."
        )
    try:
        composition = compose(args.workspace_root)
        composition.profile_service.initialize_metadata()
    except ProfileManagerError as error:
        raise SystemExit(str(error)) from error
    print(f"revamped development composition ready: {composition.paths.root}")
    print("No browser process was launched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
