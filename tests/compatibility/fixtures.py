"""Safe synthetic workspaces for compatibility tests.

Fixtures are rooted below the repository's ignored ``tmp`` directory and never
point at the live application directories.
"""

from pathlib import Path
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = PROJECT_ROOT / "tmp"


class DisposableWorkspace:
    """Context manager for a temporary, repository-local test workspace."""

    def __init__(self, prefix="compatibility-"):
        TEST_ROOT.mkdir(exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(prefix=prefix, dir=TEST_ROOT)
        self.root = Path(self._temporary.name).resolve()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if not self.root.is_relative_to(TEST_ROOT.resolve()):
            raise AssertionError("Disposable workspace escaped the repository tmp root")
        if self.root == TEST_ROOT.resolve():
            raise AssertionError("Disposable workspace must not be the tmp root itself")
        return self._temporary.__exit__(exc_type, exc_value, traceback)

    def child(self, *parts):
        """Return a path below this fixture without creating it."""
        candidate = self.root.joinpath(*parts)
        if not candidate.is_relative_to(self.root):
            raise AssertionError("Fixture child escaped its workspace")
        return candidate


def synthetic_account(index=1):
    """Return a clearly non-production account fixture identifier."""
    return {
        "email": f"fixture-{index}@example.invalid",
        "password": f"synthetic-password-{index}",
        "totp_secret": f"SYNTHETIC{index}",
    }

