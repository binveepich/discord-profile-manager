"""Check that frozen reference sources still match the R0 hashes.

Only source files named in the R0 freeze record are read. This script does not
inspect configuration, profiles, logs, extensions, or the browser runtime.
"""

from hashlib import sha1
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FROZEN = {
    "legacy/profile_manager.py": "7c4d20b868e47e2be8a9293df78a4d13a63bbeae",
    "main.py": "1dd57b45b1c4bfbb574818816e1f3251001d56e0",
    "tests/test_m1_runtime.py": "c9321395af0d36775f00dd612617cc43cca18d5c",
    "tests/test_m2_lifecycle.py": "aa5a3b8635651bca3fb01ca7b6dc364443dc5941",
    "tests/test_m3_migration.py": "60a8831eac1bbef47f780c4c1e1ce4ac0cae697b",
    "tests/test_m4_metadata.py": "738a92e04689760b2383ec2f7856d680170d2ec9",
    "tests/test_m5_extensions.py": "944be25e6c3f3c9d771a4644f30e3e6ffe85a2b9",
    "tests/test_m6_gui.py": "1ba6f5f1e9c5fec23044222325bb6d88368503c4",
    "tests/test_m7_environment.py": "f44b0fa59adb00501d6633a3c9939b3858d7c76d",
    "tests/test_m8_proxy.py": "68b98fa6112c130f4efb747c045f2a1b8e3ac151",
}


def git_blob_hash(path):
    """Calculate the Git blob SHA-1 without invoking Git or modifying files."""
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return sha1(header + data).hexdigest()


def check():
    failures = []
    for relative, expected in FROZEN.items():
        path = PROJECT_ROOT / relative
        try:
            actual = git_blob_hash(path)
        except OSError:
            failures.append(f"MISSING OR UNREADABLE: {relative}")
            continue
        if actual != expected:
            failures.append(f"CHANGED: {relative}")
    if failures:
        print("PROTECTED SOURCE INTEGRITY: FAIL")
        for failure in failures:
            print(failure)
        return False
    print("PROTECTED SOURCE INTEGRITY: PASS")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if check() else 1)

