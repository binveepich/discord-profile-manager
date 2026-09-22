"""Disposable composition for the parallel implementation.

The stable application entrypoint is still the repository-root ``main.py``.
This module deliberately requires an explicit disposable workspace before it
constructs stateful services.
"""

from dataclasses import dataclass
import argparse
import logging
from pathlib import Path

from .accounts import (
    ACCOUNT_MODE_DEVELOPMENT,
    ACCOUNT_MODE_PRODUCT,
    AccountCompatibilityService,
    normalize_account_mode,
)
from .core import (
    ProfileManagerError,
    ProjectPaths,
    WORKSPACE_DEVELOPMENT,
    WORKSPACE_PRODUCT,
    normalize_workspace_kind,
    prepare_product_workspace,
    resolve_workspace_root,
)
from .extensions import ExtensionService
from . import environment
from .gui import ProfileGUIController, TkRevampedApp
from .launcher import ChromiumLauncher
from .processes import ChromiumProcessInspector
from .profiles import ProfileService
from .storage import LegacyStateStore, ProfileCatalogStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISPOSABLE_ROOT = PROJECT_ROOT / "tmp"


@dataclass(frozen=True)
class RevampedComposition:
    """Explicitly wired disposable services with a selected account mode."""

    paths: ProjectPaths
    logger: logging.Logger
    catalog_store: ProfileCatalogStore
    legacy_store: LegacyStateStore
    process_inspector: ChromiumProcessInspector
    profile_service: ProfileService
    extension_service: ExtensionService
    account_service: AccountCompatibilityService
    account_mode: str
    workspace_kind: str
    launcher: ChromiumLauncher
    controller: ProfileGUIController
    # Product mode keeps the conservative metadata-only service available to
    # older callers and uses this explicit service for the approved v1
    # per-profile Autofill config workflow.
    credential_service: AccountCompatibilityService | None = None


def _safe_workspace_root(value):
    DISPOSABLE_ROOT.mkdir(parents=True, exist_ok=True)
    return resolve_workspace_root(
        value,
        allowed_parent=DISPOSABLE_ROOT,
        description="disposable workspace",
    )


def _safe_product_root(value):
    live_roots = (
        PROJECT_ROOT / "profiles",
        PROJECT_ROOT / "config",
        PROJECT_ROOT / "data",
        PROJECT_ROOT / "legacy" / "data",
        PROJECT_ROOT / "legacy" / "log",
        PROJECT_ROOT / "logs",
        PROJECT_ROOT / "browser",
    )
    return prepare_product_workspace(value, forbidden_roots=live_roots)


def compose(
    workspace_root,
    *,
    process_inspector=None,
    process_factory=None,
    logger=None,
    account_mode=ACCOUNT_MODE_DEVELOPMENT,
    workspace_kind=WORKSPACE_DEVELOPMENT,
):
    """Build services below an explicitly selected development/product root."""
    workspace_kind = normalize_workspace_kind(workspace_kind)
    account_mode = normalize_account_mode(account_mode)
    if workspace_kind == WORKSPACE_DEVELOPMENT:
        root = _safe_workspace_root(workspace_root)
        if account_mode == ACCOUNT_MODE_PRODUCT:
            raise ProfileManagerError(
                "Product account mode requires --product-root and an explicit product workspace."
            )
    else:
        if account_mode != ACCOUNT_MODE_PRODUCT:
            raise ProfileManagerError(
                "Product workspaces require Interactive Product Mode."
            )
        root = _safe_product_root(workspace_root)
    paths = ProjectPaths(root, assets_root=PROJECT_ROOT)
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
        account_mode=account_mode,
        allow_synthetic_credentials=False,
    )
    launcher = ChromiumLauncher(
        paths,
        profile_service,
        extension_service=extension_service,
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
    controller.workspace_kind = workspace_kind
    return RevampedComposition(
        paths=paths,
        logger=log,
        catalog_store=catalog_store,
        legacy_store=legacy_store,
        process_inspector=inspector,
        profile_service=profile_service,
        extension_service=extension_service,
        account_service=account_service,
        account_mode=account_mode,
        workspace_kind=workspace_kind,
        launcher=launcher,
        controller=controller,
    )


def compose_product(product_root, **kwargs):
    """Compose Product mode only when the caller names the product root."""
    kwargs["account_mode"] = ACCOUNT_MODE_PRODUCT
    kwargs["workspace_kind"] = WORKSPACE_PRODUCT
    return compose(product_root, **kwargs)


def compose_product_candidate(product_root=None, *, logger=None, process_inspector=None,
                              process_factory=None):
    """Compose the React product candidate against an explicit state root.

    The default root is the repository folder because the source-first product
    is intended to be run directly from this checkout.  Tests should always
    pass a disposable root.  Repository assets (Chromium and master extension
    sources) remain read-only inputs; profile/config state stays under the
    selected root.
    """
    root = Path(product_root or PROJECT_ROOT).absolute()
    paths = ProjectPaths(root, assets_root=PROJECT_ROOT)
    log = logger or logging.getLogger("discord-profile-manager.product")
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
    metadata_account_service = AccountCompatibilityService(
        paths,
        profile_service,
        extension_service,
        process_inspector=inspector,
        logger=log,
        account_mode=ACCOUNT_MODE_PRODUCT,
        allow_synthetic_credentials=False,
    )
    credential_service = AccountCompatibilityService(
        paths,
        profile_service,
        extension_service,
        process_inspector=inspector,
        logger=log,
        account_mode=ACCOUNT_MODE_DEVELOPMENT,
        allow_synthetic_credentials=True,
    )
    launcher = ChromiumLauncher(
        paths,
        profile_service,
        extension_service=extension_service,
        process_inspector=inspector,
        process_factory=process_factory,
        environment_argument_builder=environment.product_environment_launch_arguments,
        environment_notes_builder=environment.product_environment_runtime_notes,
        logger=log,
    )
    controller = ProfileGUIController(
        profile_service,
        metadata_account_service,
        launcher,
        extension_service,
        process_inspector=inspector,
        logger=log,
    )
    controller.workspace_kind = WORKSPACE_PRODUCT
    return RevampedComposition(
        paths=paths,
        logger=log,
        catalog_store=catalog_store,
        legacy_store=legacy_store,
        process_inspector=inspector,
        profile_service=profile_service,
        extension_service=extension_service,
        account_service=metadata_account_service,
        account_mode=ACCOUNT_MODE_PRODUCT,
        workspace_kind=WORKSPACE_PRODUCT,
        launcher=launcher,
        controller=controller,
        credential_service=credential_service,
    )


def _create_tk_root():
    """Create the real Tk root at the GUI boundary for easy headless mocking."""
    import tkinter as tk

    return tk.Tk()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Disposable-workspace revamped development composition")
    parser.add_argument(
        "--workspace-root",
        help="development state root below repository tmp/",
    )
    parser.add_argument(
        "--product-root",
        help=(
            "explicit product state root; existing unmarked state is refused and "
            "repository live directories are never inferred"
        ),
    )
    parser.add_argument(
        "--allow-browser-launch",
        action="store_true",
        help="explicitly allow the launcher to target the disposable workspace runtime",
    )
    parser.add_argument(
        "--account-mode",
        choices=("development", "product", "interactive", "synthetic", "safe"),
        default=None,
        help=(
            "account UX mode: development keeps synthetic @example.invalid inputs; "
            "product persists only non-sensitive account metadata"
        ),
    )
    parser.add_argument(
        "--product-mode",
        action="store_const",
        dest="account_mode",
        const="product",
        help="shortcut for --account-mode product",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="initialize the disposable composition and exit without creating Tk",
    )
    args = parser.parse_args(argv)
    if args.workspace_root is not None and args.product_root is not None:
        raise SystemExit("Choose either --workspace-root or --product-root, not both.")
    if args.workspace_root is None and args.product_root is None:
        raise SystemExit(
            "revamped.main requires an explicit --workspace-root below tmp/ or --product-root. "
            "no stateful development operation was run."
        )
    workspace_root = args.workspace_root or args.product_root
    workspace_kind = WORKSPACE_PRODUCT if args.product_root is not None else WORKSPACE_DEVELOPMENT
    if args.product_root is not None:
        requested_mode = (
            normalize_account_mode(args.account_mode)
            if args.account_mode is not None
            else None
        )
        if requested_mode is not None and requested_mode != ACCOUNT_MODE_PRODUCT:
            raise SystemExit(
                "--product-root selects Product Mode; do not combine it with another account mode."
            )
        account_mode = ACCOUNT_MODE_PRODUCT
    else:
        account_mode = args.account_mode or ACCOUNT_MODE_DEVELOPMENT
    try:
        if args.allow_browser_launch:
            inspector = ChromiumProcessInspector()
        else:
            inspector = ChromiumProcessInspector(process_iter=lambda *_: [])
        composition = compose(
            workspace_root,
            process_inspector=inspector,
            account_mode=account_mode,
            workspace_kind=workspace_kind,
        )
        composition.profile_service.initialize_metadata()
    except ProfileManagerError as error:
        raise SystemExit(str(error)) from error

    if args.no_gui:
        label = "product" if composition.workspace_kind == WORKSPACE_PRODUCT else "development"
        print(f"revamped {label} composition ready: {composition.paths.root}")
        print("No browser process was launched.")
        return 0

    try:
        root = _create_tk_root()
        app = TkRevampedApp(
            root,
            composition.controller,
            allow_browser_launch=args.allow_browser_launch,
        )
        app.start()
        root.mainloop()
    except SystemExit:
        raise
    except Exception as error:
        try:
            root.destroy()
        except (AttributeError, UnboundLocalError):
            pass
        raise SystemExit(f"Could not start revamped development GUI: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
