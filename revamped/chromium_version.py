"""The Chromium build that this application pins.

This module imports nothing from the rest of the application. The environment
policy and the browser runtime manager both read the pin from here, so neither
has to import the other.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# The runtime location for this checkout. ProjectPaths.browser_exe resolves to the same file.
DEFAULT_BROWSER_EXE = PROJECT_ROOT / "browser" / "chrome.exe"

# The build a first install downloads, and the build the app is tested with. Change it here.
PINNED_TAG = "152.0.7977.82-1.1"
PINNED_VERSION = PINNED_TAG.split("-", 1)[0]
