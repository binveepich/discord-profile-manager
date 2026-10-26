"""Small safety tests for the Git-ref release exporter."""

from __future__ import annotations

import json
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORTER = PROJECT_ROOT / "scripts" / "export_release.py"
SOURCE_MANIFEST = PROJECT_ROOT / "scripts" / "release_manifest.json"


class ExportReleaseTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def run_export(self, repo: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(repo / "scripts" / "export_release.py"),
             "--ref", "HEAD", "--version", "0.0.0-test", "--dry-run"],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_optional_token_extractor_is_not_a_runtime_blocker_or_release_input(self) -> None:
        spec = importlib.util.spec_from_file_location("export_release_safety", EXPORTER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)

        manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        source = PROJECT_ROOT / "revamped" / "extensions.py"
        files = {"revamped/extensions.py": source.read_bytes()}
        included = {
            "revamped/extensions.py",
            "extensions/discord-autofill-extension/manifest.json",
        }
        token_source = "extensions/discord-token-extractor-extension/manifest.json"

        self.assertEqual(exporter.check_runtime_blockers(files, included), [])
        self.assertFalse(exporter.matches_any(token_source, manifest["allowlist"]))
        self.assertTrue(exporter.matches_any(token_source, manifest["denylist"]))
        self.assertTrue(exporter.matches_any(token_source, manifest["source_only_optional"]))

    def test_git_ref_allowlist_token_scan_and_untracked_exclusion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dpm-export-test-") as temp_name:
            repo = Path(temp_name)
            (repo / "scripts").mkdir()
            shutil.copy2(EXPORTER, repo / "scripts" / "export_release.py")
            manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
            manifest["allowlist"] = ["revamped/**"]
            manifest["generated"] = []
            (repo / "scripts" / "release_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (repo / "revamped").mkdir()
            (repo / "revamped" / "allowed.py").write_text('print("safe")\n', encoding="utf-8")
            (repo / "profiles" / "profile_0001").mkdir(parents=True)
            (repo / "profiles" / "profile_0001" / "Preferences").write_text("fixture data\n", encoding="utf-8")

            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.name", "Release Test")
            self.git(repo, "config", "user.email", "release-test@example.invalid")
            self.git(repo, "add", "scripts/export_release.py", "scripts/release_manifest.json",
                     "revamped/allowed.py", "profiles/profile_0001/Preferences")
            self.git(repo, "commit", "-qm", "fixture")

            untracked = repo / "revamped" / "untracked.py"
            untracked.write_text('print("untracked")\n', encoding="utf-8")
            first = self.run_export(repo)
            combined = first.stdout + first.stderr
            self.assertEqual(first.returncode, 0, combined)
            included = combined.split("Would include:\n", 1)[1].split("Excluded archived paths:", 1)[0]
            self.assertEqual([line.strip() for line in included.splitlines() if line.startswith("  ")],
                             ["revamped/allowed.py"])
            self.assertIn("profiles/profile_0001/Preferences", combined)
            self.assertNotIn("revamped/untracked.py", combined)
            self.assertIn("Hard denylist hits: 0", combined)

            fake_token = "A" * 24 + "." + "B" * 6 + "." + "C" * 27
            (repo / "revamped" / "allowed.py").write_text(f"TOKEN = {fake_token!r}\n", encoding="utf-8")
            self.git(repo, "add", "revamped/allowed.py")
            self.git(repo, "commit", "-qm", "add fake token fixture")
            second = self.run_export(repo)
            second_output = second.stdout + second.stderr
            self.assertNotEqual(second.returncode, 0, second_output)
            self.assertIn("revamped/allowed.py:1: Discord token", second_output)
            self.assertIn("[REDACTED]", second_output)
            self.assertNotIn(fake_token, second_output)


if __name__ == "__main__":
    unittest.main()
