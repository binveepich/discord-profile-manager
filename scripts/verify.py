"""Run the safe source-tree verification workflow.

This script intentionally reports only structural results. It does not read or
print profile data, application metadata, account configuration, or logs.
"""

from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "main.py"
BROWSER_EXE = PROJECT_ROOT / "browser" / "chrome.exe"


def _python_files():
    paths = [
        ENTRYPOINT,
        PROJECT_ROOT / "legacy" / "profile_manager.py",
        *sorted((PROJECT_ROOT / "tests").glob("*.py")),
        Path(__file__).resolve(),
    ]
    return [path for path in paths if path.is_file()]


def _syntax_check():
    try:
        for path in _python_files():
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
    except (OSError, SyntaxError, UnicodeError):
        return False
    return True


def _entrypoint_check():
    if not ENTRYPOINT.is_file():
        return False
    try:
        source = ENTRYPOINT.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return (
        "from revamped import product_main" in source
        and '"--legacy"' in source
        and 'if __name__ == "__main__":' in source
        and "main()" in source
    )


def _runtime_structure_check():
    # Structural presence only: do not inspect the runtime or start Chromium.
    return BROWSER_EXE.is_file()


def _unit_test_check():
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def main():
    results = {
        "SYNTAX": _syntax_check(),
        "UNIT TESTS": _unit_test_check(),
        "ENTRYPOINT": _entrypoint_check(),
        "RUNTIME STRUCTURE": _runtime_structure_check(),
    }
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    gate_passed = all(results.values())
    print(f"AUTONOMOUS GATE: {'PASS' if gate_passed else 'FAIL'}")
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
