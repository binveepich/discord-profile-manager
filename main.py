"""Entrypoint for Discord Profile Manager.

``python main.py`` starts the React + pywebview product, using the same startup
as ``python -m revamped.product_main``. ``python main.py --legacy`` starts the
legacy Tkinter app, which remains runnable but is no longer the default.
"""

import sys

from revamped import product_main


LEGACY_FLAG = "--legacy"
# These options never open a window, so they work without the frontend build.
NO_WINDOW_OPTIONS = {"--no-gui", "-h", "--help"}
FRONTEND_BUILD_MESSAGE = (
    "The React frontend is not built yet (frontend/dist/index.html is missing).\n"
    "Build it once from the project folder, then run python main.py again:\n"
    "    cd frontend\n"
    "    npm ci\n"
    "    npm run build\n"
    "To use the legacy app in the meantime, run: python main.py --legacy"
)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if LEGACY_FLAG in args:
        if args != [LEGACY_FLAG]:
            raise SystemExit(f"{LEGACY_FLAG} starts the legacy app and takes no other arguments.")
        # Imported only on this branch: importing the legacy module configures
        # its file logging, and the product start must not depend on it.
        from legacy.profile_manager import main as legacy_main

        return legacy_main()
    if not NO_WINDOW_OPTIONS.intersection(args) and not product_main.FRONTEND_INDEX.is_file():
        raise SystemExit(FRONTEND_BUILD_MESSAGE)
    return product_main.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
