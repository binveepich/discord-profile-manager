"""Regenerate a clean source-only product snapshot from an allowlist.

This script intentionally does not run as part of normal development and does
not publish the official accepted final snapshot. The output is disposable; it
is never an independently maintained codebase.
"""

import argparse
import json
from pathlib import Path
import shutil


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = PROJECT_ROOT / "final"
PYTHON_MODULES = (
    "__init__.py", "accounts.py", "core.py", "environment.py", "extensions.py",
    "launcher.py", "models.py", "processes.py", "profiles.py", "product_api.py",
    "product_main.py", "storage.py",
)


def _copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def build_snapshot(output, *, include_browser=False):
    output = Path(output).absolute()
    if output == PROJECT_ROOT or (PROJECT_ROOT in output.parents and output != FINAL_DIR):
        raise ValueError("Snapshot output must be the disposable repository final/ directory or an external directory.")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Snapshot output exists and is not empty; choose a disposable output directory.")
    output.mkdir(parents=True, exist_ok=True)

    for name in PYTHON_MODULES:
        _copy_file(PROJECT_ROOT / "revamped" / name, output / "revamped" / name)
    (output / "main.py").write_text(
        "from revamped.product_main import main\n\n"
        "if __name__ == \"__main__\":\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    frontend_dist = PROJECT_ROOT / "frontend" / "dist"
    if not frontend_dist.is_dir():
        raise FileNotFoundError("frontend/dist is missing; run npm run build first.")
    shutil.copytree(frontend_dist, output / "frontend" / "dist")
    shutil.copy2(PROJECT_ROOT / "requirements.txt", output / "requirements.txt")

    autofill_source = PROJECT_ROOT / "extensions" / "discord-autofill-extension"
    shutil.copytree(autofill_source, output / "extensions" / autofill_source.name)
    if include_browser:
        browser = PROJECT_ROOT / "browser"
        if not browser.is_dir():
            raise FileNotFoundError("browser/ is not available for --include-browser.")
        shutil.copytree(browser, output / "browser")

    (output / "run.bat").write_text(
        "@echo off\r\npython -m revamped.product_main\r\n",
        encoding="utf-8",
    )
    (output / "README.txt").write_text(
        "Run: install requirements.txt, then run run.bat.\r\n"
        "Profiles and config are created beside this source snapshot.\r\n",
        encoding="utf-8",
    )
    manifest = {
        "version": 1,
        "source": "regenerated from Discord_Profile_Manager allowlist",
        "includes_browser_runtime": bool(include_browser),
        "excluded": [
            "profiles", "config/profiles.json", "logs", "tests", "tmp",
            "legacy", "extensions/discord-token-extractor-extension",
            "*.rar", "cookies", "sessions", "stored credentials",
        ],
    }
    (output / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a disposable product source snapshot")
    parser.add_argument("output", type=Path)
    parser.add_argument("--include-browser", action="store_true")
    args = parser.parse_args(argv)
    print(build_snapshot(args.output, include_browser=args.include_browser))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
