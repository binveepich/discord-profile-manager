"""Source-first entrypoint for the React + pywebview product candidate."""

import argparse
import logging
from pathlib import Path

from .main import PROJECT_ROOT, compose_product_candidate
from .product_api import ProductAPI


FRONTEND_INDEX = PROJECT_ROOT / "frontend" / "dist" / "index.html"
PRODUCT_WINDOW_WIDTH = 1600
PRODUCT_WINDOW_HEIGHT = 900


def main(argv=None):
    parser = argparse.ArgumentParser(description="Discord Profile Manager product candidate")
    parser.add_argument(
        "--root",
        default=str(PROJECT_ROOT),
        help="profile/config state root (defaults to this checkout)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="initialize the product API and print a safe status without opening a window",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).absolute()
    composition = compose_product_candidate(root)
    composition.profile_service.initialize_metadata()
    api = ProductAPI(composition)
    if args.no_gui:
        print(f"Discord Profile Manager product candidate ready: {root}")
        print(f"Profiles: {len(api.list_profiles())}")
        print(f"Runtime: {api.get_runtime_info()['browser_version']}")
        api.shutdown()
        return 0
    if not FRONTEND_INDEX.is_file():
        api.shutdown()
        raise SystemExit(
            "Frontend build not found. Run `npm install` and `npm run build` in frontend/ first."
        )
    try:
        import webview
    except ImportError as error:
        api.shutdown()
        raise SystemExit(
            "pywebview is not installed. Install requirements.txt, then run this command again."
        ) from error

    try:
        webview.create_window(
            "Discord Profile Manager",
            FRONTEND_INDEX.as_uri(),
            js_api=api,
            width=PRODUCT_WINDOW_WIDTH,
            height=PRODUCT_WINDOW_HEIGHT,
            resizable=False,
        )
        webview.start(debug=False)
    finally:
        api.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
