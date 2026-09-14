# Discord Profile Manager

Windows desktop profile manager using the bundled Ungoogled Chromium runtime at
`browser/chrome.exe`. Keep the complete runtime in `browser/`; that directory is
intentionally ignored by Git. The manager does not install or update Chromium.

## Run

Use Python with Tkinter and the existing `psutil` dependency. The M1 tests were run
with Python 3.11.8 and psutil 7.2.2 on Windows. If psutil is missing, install it in
your chosen Python environment with `python -m pip install psutil`.

From PowerShell:

```powershell
Set-Location -LiteralPath 'I:\Discord_Profile_Manager'
python -B .\legacy\profile_manager.py
```

The script resolves browser and extension source paths relative to the project
root, independent of the working directory. If `browser/chrome.exe` is missing
or is a directory instead of a file, startup displays the expected full path and
returns after the error dialog is dismissed. A missing runtime encountered when
opening a profile uses the existing GUI error dialog.

## M1/M2 storage compatibility

- Profiles remain at `legacy/data/<profile ID>/`.
- The manager registry remains at `legacy/data/Local State`, with its existing format.
- Logs remain at `legacy/log/`.
- Extension sources are read from root `extensions/` and copied into each profile's
  `Unpacked Extensions/` directory by the existing account workflow.
- Existing per-profile extension copies and account configuration are retained.
- Each launch keeps `--user-data-dir=<legacy/data/profile ID>` and the existing
  launch flags, extension arguments, and Discord URL.

M2 does not relocate existing data, introduce `profiles.json`, or add presets,
proxies, an updater, or new application modules. Legacy profile data and logs
remain excluded from Git. Chromium runtime files are unchanged.

## M2 lifecycle behavior

- New profiles initialize `Default/Preferences` inside their existing user-data
  root. Existing root-level legacy preferences are not moved or overwritten.
- IDs are checked against both the registry and existing directories/files.
  A failed creation can leave an unregistered directory, which is retained and
  never reused automatically.
- Opening requires a registered ID and its existing directory. Missing data is
  reported rather than replaced with an empty browser session.
- Windows path aliases, case-colliding IDs, traversal, and links/junctions along
  managed paths are rejected. Extension paths must belong to the selected profile.
- Open supports multiple selected profiles. Each receives its own user-data root;
  a failure for one does not prevent the others from being requested. Already
  running profiles are reported and skipped; their windows are not brought forward.
- Running-browser checks inspect live processes, so they also work after manager
  restart. A running profile can be renamed but must be closed before deletion or
  account preference changes. Uninspectable browser processes produce a clear error.
- `Default` selection works by ID, independent of its star icon. Refresh preserves
  selected IDs; malformed metadata clears stale rows and displays an error.
- Invalid JSON/schema, unreadable metadata, and a missing registry alongside
  existing directories never trigger an automatic reset. Correct or restore the
  registry, then restart or refresh. Unknown valid fields are preserved.
- A small `.manager.lock` file serializes manager profile mutations and launches.
  Stale metadata saves are rejected. Keep other software from editing this registry
  while manager operations are in progress.
- Confirmed deletion first renames the directory to `.deleting-<ID>-<unique suffix>`
  under `legacy/data/`, then updates the registry and removes the staged directory.
  If the metadata save fails, the original directory is restored. A crash or failed
  cleanup can leave staged data; its location is reported and it is never cleaned
  automatically on restart. Inspect it before attempting recovery or removal.

Compatibility is supported for the existing manager's unopened profiles and for
complete independent Chromium user-data roots. A legacy folder containing browser
session files directly at its top level is treated as a shared-root subprofile and
blocked with an explanatory error. Ambiguous layouts, invalid browser Local State,
and missing last-used internal directories are also blocked. M2 does not move those
files or guess a replacement data root; such layouts require a separate migration.

## Automated checks

```powershell
python -B -m unittest discover -s tests -v
```

The unit tests use synthetic data in isolated directories under `tmp/`, suppress legacy
import-time log setup, and mock browser process creation and GUI dialogs. They
do not open Chromium or access production account data. They cover startup,
launch errors, Windows argument parsing, isolated launch paths, extension
arguments, existing Local State preservation, profile operations, and account
import/storage, lifecycle failures, process detection, and multi-profile opening.

An additional opt-in test launches the real runtime in headless mode against a
loopback HTTP fixture, using only disposable workspace profiles:

```powershell
python -B tests/browser_smoke_m2.py
```

Run this in a normal Windows terminal: a restricted execution sandbox can prevent
Chromium's child processes from starting. This test checks concurrent profile
opening, cookie/Local Storage/IndexedDB separation, browser and manager restarts,
rename persistence, and preservation of one profile when another is deleted.
Test directories are removed on success and retained under `tmp/` on failure.
It does not test Discord login or visible GUI behavior.

## Exact manual acceptance checks

Use disposable profiles for creation, account import, rename, and deletion.
Close a disposable profile's browser windows before deleting it.

1. **Startup:** Run the command above. Confirm the existing manager window opens.
2. **Create and launch:** Create `M1 Test A` and `M1 Test B`; decline account setup.
   Select only `M1 Test A`, click Open Discord, and confirm Discord opens. Visit
   `chrome://version` in that window. Its executable path must end with
   `Discord_Profile_Manager\browser\chrome.exe`; for this fresh profile, its
   profile path should end with `legacy\data\Profile N\Default`. Record the ID.
3. **Isolation:** Add a harmless bookmark named `M1 A marker` in A. Open B from
   the manager while A is still open. Verify a different `Profile N` path in
   `chrome://version` and that B does not contain A's bookmark.
4. **Rename and restart:** Close both browser windows. Rename A to
   `M1 Test A renamed`. Close and restart the manager, then open the renamed
   profile. Its ID/path and bookmark must be unchanged.
5. **Account import:** In PowerShell at the project root, create a synthetic file:

   ```powershell
   New-Item -ItemType Directory -Path .\tmp -Force | Out-Null
   @'
   m1-one@example.invalid:synthetic-password-one
   m1-two@example.invalid:synthetic-password-two
   '@ | Set-Content -LiteralPath .\tmp\m1-accounts.txt -Encoding ASCII
   ```

   Click Import TXT and choose `tmp\m1-accounts.txt`. Confirm two profiles are
   added with numbered names containing `m1-one` and `m1-two`. Use View Account
   to verify the respective synthetic email addresses. Restart the manager and
   confirm they remain assigned.
6. **Extension loading:** Open one imported test profile. Visit
   `chrome://extensions` and confirm Discord Autofill is loaded. Visit Discord's
   login page and check that the synthetic fields are populated; do not submit
   them. Confirm the other imported profile uses its own synthetic account.
7. **Deletion:** Close the test profile's browser windows. Select only `M1 Test B`,
   click Delete, and first cancel. Confirm it remains. Repeat and confirm deletion.
   Restart the manager and verify B is gone while A and the imported tests remain.
   Remove remaining disposable profiles only when you are finished testing.
8. **Different working directory:** Close the manager and run:

   ```powershell
   Set-Location -LiteralPath 'I:\Discord_Profile_Manager\config'
   python -B '..\legacy\profile_manager.py'
   ```

   Confirm the same profiles appear and launching still finds root `browser/chrome.exe`.
9. **Missing runtime, without changing the real browser:** Close the manager and
   create a script-only test copy inside the workspace:

   ```powershell
   Set-Location -LiteralPath 'I:\Discord_Profile_Manager'
   New-Item -ItemType Directory -Path '.\tmp\M1 Missing Browser\legacy' -Force | Out-Null
   Copy-Item -LiteralPath '.\legacy\profile_manager.py' -Destination '.\tmp\M1 Missing Browser\legacy\profile_manager.py'
   python -B '.\tmp\M1 Missing Browser\legacy\profile_manager.py'
   ```

   Do not copy a runtime into this test folder. Expect a `Browser runtime not found`
   dialog mentioning
   `I:\Discord_Profile_Manager\tmp\M1 Missing Browser\browser\chrome.exe`.
   Dismiss it; the process should finish without a traceback or a console input
   prompt. The real `browser/` and `legacy/data/` directories are unaffected.

Actual session preservation for an older external installation still requires
validation against its known browser profile path. M2 does not guess or migrate
external storage layouts.

## Additional M2 manual checklist

Use the disposable profiles from the checklist above. For intentional metadata or
directory damage, use a separate disposable application copy with no real accounts.

1. Select A and B together with Ctrl-click and Open. Confirm two distinct profile
   paths in `chrome://version`; repeat Open and confirm they are reported as already
   running instead of launching duplicate instances.
2. Keep both browsers open, close/restart the manager, then attempt to delete A.
   Expect a close-Chromium message and no loss of either profile. Close A and retry;
   B must remain intact and usable.
3. Rename a running disposable profile. Its manager label should change while its
   browser path and stored bookmark remain unchanged. Close/reopen Chromium and
   confirm persistence.
4. In the disposable application copy, close browsers and temporarily rename one
   registered profile directory to an unused backup name. Select that profile and
   a valid profile together, then Open. Expect an error for the missing directory,
   no replacement directory, and a successful launch request for the valid one.
   Restore the original directory name while browsers are closed and retry.
5. In that copy only, back up `legacy/data/Local State`, replace it with invalid JSON,
   and restart. Expect a clear metadata error. Try Create: the invalid file must
   remain unchanged. Restore the exact backup and Refresh; profiles should return.
6. Test a disposable `Default` entry and a project folder containing spaces/Unicode.
   Verify selection, rename, opening, and confirmed deletion work for the intended ID.
7. Test an approved copy of an existing independent legacy user-data root. Confirm
   the original `chrome://version` profile path, bookmark, and storage survive restart.
   A shared-root subprofile or ambiguous layout must show an explanatory error and
   remain untouched; do not attempt migration as part of M2.
