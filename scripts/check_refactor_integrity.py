"""Verify the immutable R0 source baseline and explicit milestone deltas.

The R0 baseline is never replaced when a protected file changes. A protected
file may either still match its immutable R0 blob or match a separately named,
reviewed milestone blob. Any other modification, deletion, rename, or
protected untracked path fails closed.
"""

from hashlib import sha1
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]
R0_BASELINE_COMMIT = "ca9c5661fb9cedc2ecaf884c58547a8672bfcf71"

# These are the Git blobs at the actual R0 freeze commit. They intentionally
# remain separate from later approved milestone content.
IMMUTABLE_BASELINE = {
    "legacy/profile_manager.py": "238e180952835fd87f893ca18df00ca73f6d5c67",
    "main.py": "1dd57b45b1c4bfbb574818816e1f3251001d56e0",
    "tests/test_m1_runtime.py": "00bc5d212a33ac9947f4ddfc5418bb331ed4d540",
    "tests/test_m2_lifecycle.py": "847f333b6520b44d45a4263ee36411dd6f5a7d9f",
    "tests/test_m3_migration.py": "60a8831eac1bbef47f780c4c1e1ce4ac0cae697b",
    "tests/test_m4_metadata.py": "738a92e04689760b2383ec2f7856d680170d2ec9",
    "tests/test_m5_extensions.py": "944be25e6c3f3c9d771a4644f30e3e6ffe85a2b9",
    "tests/test_m6_gui.py": "1ba6f5f1e9c5fec23044222325bb6d88368503c4",
    "tests/test_m7_environment.py": "f44b0fa59adb00501d6633a3c9939b3858d7c76d",
    "tests/test_m8_proxy.py": "68b98fa6112c130f4efb747c045f2a1b8e3ac151",
}

# R10-R12 were completed in HEAD, but their legacy compatibility changes were
# left in the working tree. They are named explicitly so the checker can
# distinguish that reviewed milestone from an arbitrary edit.
APPROVED_MILESTONE_HASHES = {
    "R10-R12 compatibility": {
        "legacy/profile_manager.py": "22a733b9741a6a59ddfa5ff24c5003b1ebf06276",
        "tests/test_m5_extensions.py": "387c767e5ab212b264bc31d1745d64186930e64b",
    },
    "R14 extension security remediation": {
        "legacy/profile_manager.py": "1cb18a41b2b43543af95b66bc80c3b2e9a8892ee",
        "tests/test_m5_extensions.py": "6a590d135847d044e2e9b36133b7095cd1b23660",
    },
    # Owner-approved beta routing: main.py starts the React product and keeps
    # the legacy app behind --legacy. The R0 blob above is unchanged.
    "Beta step 8 product entrypoint": {
        "main.py": "66b95aa3821f2978f2dceebbb796b3011e5b2477",
    },
    # Owner-approved beta step 2.5: the legacy proxy and environment dialogs are
    # repaired, and proxy editing is limited to endpoint fields. The legacy
    # module and the two tests changed with it are recorded after the repair.
    "Beta step 2.5 legacy proxy endpoint repair": {
        "legacy/profile_manager.py": "c3aca7a7cfc2b6432032fdc05146cdcf2a1f7dce",
        "tests/test_m5_extensions.py": "4360be9d05227d894f1e3da5873a1b11550c23a3",
        "tests/test_m8_proxy.py": "bfa6cf7bcef37d39f68d343e788dd6d0a0816b1e",
    },
}

# Compatibility name retained for callers that imported the old checker.
FROZEN = IMMUTABLE_BASELINE

PROTECTED_PREFIXES = (
    "profiles/",
    "data/",
    "config/profiles.json",
    "legacy/data/",
    "legacy/log/",
    "logs/",
    "browser/",
    "extensions/",
)

# The archive is a known repository-hygiene artifact from the Autofill source
# handoff.  Product operations must never read it; the extracted directory is
# the sole supported master source.  Keep the artifact visible in diagnostics
# without allowing it to make the source-integrity gate fail.
HYGIENE_ARTIFACTS = {
    "extensions/discord-autofill-extension.rar",
}


def git_blob_hash(path):
    """Calculate a Git-style source hash independent of Windows line endings."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    header = f"blob {len(data)}\0".encode("ascii")
    return sha1(header + data).hexdigest()


def _git(arguments):
    try:
        return subprocess.run(
            ["git", "-c", f"safe.directory={PROJECT_ROOT}", *arguments],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None


def _untracked_paths():
    result = _git(["ls-files", "--others", "--exclude-standard", "-z", "--"])
    if result is None or result.returncode != 0:
        return None
    try:
        output = result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return {item.replace("\\", "/") for item in output.split("\0") if item}


def _renamed_paths():
    result = _git([
        "diff", "--name-status", "--find-renames", "-z",
        R0_BASELINE_COMMIT, "--",
    ])
    if result is None or result.returncode != 0:
        return None
    try:
        fields = result.stdout.decode("utf-8").split("\0")
    except UnicodeDecodeError:
        return None
    renames = set()
    index = 0
    while index + 2 < len(fields):
        status = fields[index]
        old_path = fields[index + 1].replace("\\", "/")
        new_path = fields[index + 2].replace("\\", "/")
        index += 3
        if status.startswith("R"):
            renames.add((old_path, new_path))
    return renames


def _is_protected_path(path):
    return path in IMMUTABLE_BASELINE or any(
        path.startswith(prefix) for prefix in PROTECTED_PREFIXES
    )


def _approved_label(relative, actual):
    for milestone, files in APPROVED_MILESTONE_HASHES.items():
        if files.get(relative) == actual:
            return milestone
    return None


def classify_protected_file(relative, expected, actual=None, *, exists=True, moved_to=None, approved=None):
    """Classify one protected path for tests and human-readable diagnostics."""
    if not exists:
        if moved_to:
            return f"RENAMED/MOVED FROM BASELINE: {relative} -> {moved_to}"
        return f"DELETED OR UNREADABLE: {relative}"
    if actual == expected:
        return f"BASELINE: {relative}"
    if approved:
        return f"APPROVED {approved}: {relative}"
    return f"UNAPPROVED MODIFICATION: {relative}"


def check():
    failures = []
    baseline_object = _git(["cat-file", "-e", f"{R0_BASELINE_COMMIT}^{{commit}}"])
    if baseline_object is None or baseline_object.returncode != 0:
        failures.append(f"IMMUTABLE BASELINE COMMIT UNAVAILABLE: {R0_BASELINE_COMMIT}")

    renames = _renamed_paths()
    if renames is None:
        failures.append("Could not inspect Git rename status.")
        renames = set()

    print(f"IMMUTABLE BASELINE: R0 {R0_BASELINE_COMMIT}")
    for relative, expected in IMMUTABLE_BASELINE.items():
        path = PROJECT_ROOT / relative
        if not path.exists():
            moved_to = [new for old, new in renames if old == relative]
            failures.append(classify_protected_file(
                relative, expected, exists=False,
                moved_to=moved_to[0] if moved_to else None,
            ))
            continue
        try:
            actual = git_blob_hash(path)
        except OSError:
            failures.append(classify_protected_file(relative, expected, exists=False))
            continue
        milestone = _approved_label(relative, actual)
        result = classify_protected_file(
            relative, expected, actual, approved=milestone
        )
        if result.startswith(("BASELINE:", "APPROVED ")):
            print(result)
            continue
        failures.append(result)

    untracked = _untracked_paths()
    if untracked is None:
        failures.append("Could not inspect untracked paths.")
    else:
        for path in sorted(untracked):
            if path in HYGIENE_ARTIFACTS:
                print(f"HYGIENE ARTIFACT (ignored by product): {path}")
                continue
            if _is_protected_path(path):
                failures.append(f"UNEXPECTED PROTECTED UNTRACKED FILE: {path}")

    if failures:
        print("PROTECTED SOURCE INTEGRITY: FAIL")
        for failure in failures:
            print(failure)
        return False
    print("PROTECTED SOURCE INTEGRITY: PASS")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if check() else 1)
