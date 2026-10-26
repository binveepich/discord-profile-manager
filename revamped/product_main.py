"""Source-first entrypoint for the React + pywebview product candidate."""

import argparse
import logging
import threading
from pathlib import Path

from .main import PROJECT_ROOT, compose_product_candidate
from .product_api import ProductAPI
from .window_constraints import MIN_WINDOW_SIZE, install_aspect_ratio_constraint, remove_aspect_ratio_constraint


FRONTEND_INDEX = PROJECT_ROOT / "frontend" / "dist" / "index.html"
PRODUCT_WINDOW_WIDTH = 1600
PRODUCT_WINDOW_HEIGHT = 900
PRODUCT_WINDOW_MIN_SIZE = MIN_WINDOW_SIZE
PRODUCT_DISPLAY_NAME = "Trình quản lý đa tài khoản Discord"


def main(argv=None):
    parser = argparse.ArgumentParser(description=PRODUCT_DISPLAY_NAME)
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
    api = ProductAPI(composition)
    if args.no_gui:
        # The window path leaves the catalog write to the loading splash, which runs it after the window is shown.
        composition.profile_service.initialize_metadata()
        print(f"{PRODUCT_DISPLAY_NAME} ready: {root}")
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

    window = None
    constraints_lock = threading.Lock()
    closing_started = threading.Event()

    def remove_native_constraints_before_disposal(*_args, **_kwargs):
        # pywebview's WinForms closing event runs synchronously in FormClosing,
        # before FormClosed disposes the native Form. Return True so this
        # cleanup callback never cancels the user's close request.
        closing_started.set()
        with constraints_lock:
            remove_aspect_ratio_constraint(window)
        return True

    try:
        window = webview.create_window(
            PRODUCT_DISPLAY_NAME,
            str(FRONTEND_INDEX.resolve()),
            js_api=api,
            width=PRODUCT_WINDOW_WIDTH,
            height=PRODUCT_WINDOW_HEIGHT,
            x=None,
            y=None,
            resizable=True,
            fullscreen=False,
            maximized=False,
            min_size=PRODUCT_WINDOW_MIN_SIZE,
        )
        window.events.closing += remove_native_constraints_before_disposal

        def install_native_constraints():
            # pywebview exposes the native WinForms handle only after its
            # shown event. Serialize installation with FormClosing so a
            # late startup callback cannot subclass a closing/disposed Form.
            if window is not None and window.events.shown.wait(10):
                with constraints_lock:
                    if not closing_started.is_set():
                        install_aspect_ratio_constraint(
                            window,
                            min_size=PRODUCT_WINDOW_MIN_SIZE,
                        )

        # Serve the Vite ES-module build over pywebview's local HTTP server.
        # Loading it as file:// can prevent WebView2 from loading module assets.
        webview.start(
            func=install_native_constraints,
            debug=False,
            http_server=True,
        )
    finally:
        remove_native_constraints_before_disposal()
        api.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
