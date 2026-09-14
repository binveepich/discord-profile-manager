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

## M1/M2/M3/M4/M5 storage compatibility

- Application-owned profile metadata is stored at `config/profiles.json` with a
  versioned `profiles` list. It contains profile IDs, display names, relative
  profile directories, timestamps, and the M4 environment/proxy placeholders.
- The existing `legacy/data/Local State` registry is retained as a compatibility
  reader/mirror for M1-M3 installations. It is not the primary application
  profile catalog, and Chromium-owned Local State files inside user-data roots
  are not rewritten by M4.
- New profiles use isolated roots under `profiles/profile_0001/`,
  `profiles/profile_0002/`, and so on. The corresponding `profile_directory`
  field in `config/profiles.json` records the managed directory.
- Existing unmarked profiles continue working from `legacy/data/<profile ID>/`;
  they are never moved automatically. Logs remain at `legacy/log/`.
- `ProfileManager.migrate_profile(profile_id)` is an explicit, copy-only
  migration for a registered legacy profile. It copies to a collision-free
  `profiles/profile_####/` directory, updates both application metadata and the
  compatibility mirror only after the copy succeeds, and leaves the legacy
  source in place. A failed copy or metadata update leaves the source untouched
  and reports the paths involved.
- The supported extension source is discovered under root `extensions/`.
  `manifest.json`, `config.js`, and files declared by the manifest are validated
  before deployment.
- Because the current content-script design embeds profile-specific account
  configuration in `config.js`, each profile keeps its own unpacked deployment
  under `Unpacked Extensions/`. Reusable source files are refreshed from the
  root source while the profile's existing `config.js` is preserved.
- Each launch keeps the existing launch flags, extension arguments, and Discord
  URL while selecting the resolved legacy or managed user-data root.

M5 does not implement environment emulation, mobile behavior, proxy networking, an
updater, credential redesign, GUI/module migration, or a plugin framework. Legacy
profile data, managed profiles, and logs remain excluded from Git. Chromium runtime
files are unchanged.

## M5 extension behavior

- Account setup deploys the supported autofill extension using a staged copy, then
  writes only the selected profile's `config.js`.
- Existing profile deployments are compatible across manager restarts. Missing or
  invalid optional deployments are skipped during launch so browser profile data
  remains usable; account setup reports source/deployment errors clearly.
- Source updates replace reusable extension files without sharing account
  configuration between profiles. Extra profile-local extension files are retained.
- Account import continues to create isolated browser roots and isolated extension
  configuration for each imported synthetic account.

When `config/profiles.json` is missing or empty, the manager imports registered
M1-M3 profiles and discovers valid existing managed profile roots without
deleting or moving them. Malformed metadata is left unchanged and reported;
missing directories remain metadata entries rather than being recreated. Valid
managed folders absent from the catalog are safely re-imported. Metadata writes
use a temporary file, validation, flush, and atomic replacement.

## M2 lifecycle behavior

- New profiles initialize `Default/Preferences` inside their `profiles/profile_####`
  user-data root. Existing root-level legacy preferences are not moved or
  overwritten.
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
- Invalid JSON/schema and unreadable metadata never trigger an automatic reset.
  Correct or restore the affected file, then restart or refresh. Unknown valid
  application fields are preserved; sensitive credential/session fields are
  rejected from `profiles.json`.
- A small `.manager.lock` file serializes manager profile mutations and launches.
  Stale metadata saves are rejected. Keep other software from editing this registry
  while manager operations are in progress.
- Confirmed deletion first renames the active directory to
  `.deleting-<ID>-<unique suffix>` beside that directory, then updates the
  registry and removes the staged directory.
  If the metadata save fails, the original directory is restored. A crash or failed
  cleanup can leave staged data; its location is reported and it is never cleaned
  automatically on restart. Inspect it before attempting recovery or removal.

Compatibility is supported for the existing manager's unopened profiles and for
complete independent Chromium user-data roots. A legacy folder containing browser
session files directly at its top level is treated as a shared-root subprofile and
blocked with an explanatory error. Ambiguous layouts, invalid browser Local State,
and missing last-used internal directories are also blocked. M3's explicit copy
migration rejects links and path collisions and never removes the legacy source.

## Automated checks

```powershell
python -B -m unittest discover -s tests -v
```

The unit tests use synthetic data in isolated directories under `tmp/`, suppress legacy
import-time log setup, and mock browser process creation and GUI dialogs. They
do not open Chromium or access production account data. They cover startup,
launch errors, Windows argument parsing, isolated launch paths, extension
arguments, existing Local State preservation, profile operations, account
import/storage, lifecycle failures, process detection, multi-profile opening,
copy-only legacy-to-`profiles/` migration safeguards, and application-owned
metadata recovery/atomic-write safeguards.

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

The headless smoke test is also sensitive to the local Chromium build and Windows
graphics environment. On some hosts, Chromium can fail during GPU persistent-cache
initialization with a sharing violation (`0x20`) and exit with `0x80000003` before
the fixture page loads. This is an environment-specific smoke-test limitation;
normal GUI launches through the manager should be validated separately.

## Exact manual acceptance checks

Use disposable profiles for creation, account import, rename, and deletion.
Close a disposable profile's browser windows before deleting it.

1. **Startup:** Run the command above. Confirm the existing manager window opens.
2. **Create and launch:** Create `M1 Test A` and `M1 Test B`; decline account setup.
   Select only `M1 Test A`, click Open Discord, and confirm Discord opens. Visit
   `chrome://version` in that window. Its executable path must end with
   `Discord_Profile_Manager\browser\chrome.exe`; for this fresh profile, its
   profile path should end with `profiles\profile_####\Default`. Record the ID.
3. **Isolation:** Add a harmless bookmark named `M1 A marker` in A. Open B from
   the manager while A is still open. Verify a different `profile_####` path in
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
validation against its known browser profile path. M3 only migrates registered
profiles found under this application's `legacy/data/` root; it does not guess
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
   remain untouched.

## M3 migration manual checklist

Use a disposable copy of a registered legacy profile. Back up `legacy/data/Local State`
before testing migration.

1. Start with a registered profile whose directory is under `legacy/data/<ID>`.
   Open it once and verify its cookies/bookmark, then close Chromium.
2. In a Python console from the project root, call
   `ProfileManager().migrate_profile(<ID>)` using the profile's exact ID. Confirm it
   reports a `profile_####` ID, creates `profiles\profile_####`, and leaves the
   original `legacy\data\<ID>` directory and its files unchanged.
3. Restart the manager and open the migrated profile. In `chrome://version`, confirm
   the user-data path is the new `profiles\profile_####` directory and the original
   browser data remains available.
4. Call the migration operation again for the same ID. It must return the same
   managed ID without creating a second copy.
5. Create another profile and confirm it uses the next collision-free
   `profiles\profile_####` directory. Put an unrelated `profile_####` folder in
   `profiles/` and confirm the next created profile does not overwrite it.
6. With Chromium closed, temporarily replace the destination with a file or make
   the source unreadable in a disposable copy. Retry migration and confirm a clear
   error, an unchanged legacy source, and no metadata marker pointing at a missing
   destination. Restore the backup before continuing.
7. Delete a migrated disposable profile through the GUI. Confirm only its active
   `profiles\profile_####` copy is removed; the original legacy source remains because
   migration was copy-only.
