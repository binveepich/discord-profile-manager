# Discord Profile Manager

Windows desktop profile manager using the bundled Ungoogled Chromium runtime at
`browser/chrome.exe`. Keep the complete runtime in `browser/`; that directory is
intentionally ignored by Git. The manager does not install or update Chromium.

## Run

Use Python with Tkinter and the existing `psutil` dependency. The M1 tests were run
with Python 3.11.8 and psutil 7.2.2 on Windows. If psutil is missing, install it in
your chosen Python environment with `python -m pip install psutil`.

Preferred source entrypoint from PowerShell:

```powershell
Set-Location -LiteralPath 'I:\Discord_Profile_Manager'
python -B main.py
```

The legacy command remains compatible:

```powershell
python -B .\legacy\profile_manager.py
```

`main.py` is a thin wrapper; the current implementation remains in
`legacy/profile_manager.py`. The implementation resolves browser and extension
source paths relative to the project root, independent of the working directory.
If `browser/chrome.exe` is missing
or is a directory instead of a file, startup displays the expected full path and
returns after the error dialog is dismissed. A missing runtime encountered when
opening a profile uses the existing GUI error dialog.

## Packaging status

Packaging is not active yet. The application is currently intended to be run and
reviewed from source. Do not create an `.exe`, installer, portable release, or
GitHub release artifact until the user explicitly approves the source-code version.

## M1-M8 storage and launch compatibility

- Application-owned profile metadata is stored at `config/profiles.json` with a
  versioned `profiles` list. It contains profile IDs, display names, relative
  profile directories, timestamps, optional environment settings, and optional
  proxy settings.
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
- Root `extensions/` is the application-owned extension registry. Every
   subdirectory with a valid `manifest.json` is discovered deterministically;
   declared manifest files are validated before deployment. The autofill
   account workflow additionally requires its profile-specific `config.js`.
- Because the current content-script design embeds profile-specific account
  configuration in `config.js`, each profile keeps its own unpacked deployment
  under `Unpacked Extensions/`. Reusable source files are refreshed from the
  root source while the profile's existing `config.js` is preserved.
- Each launch keeps the existing launch flags, extension arguments, and Discord
  URL while selecting the resolved legacy or managed user-data root.

Legacy profile data, managed profiles, and logs remain excluded from Git.
Chromium runtime files are unchanged. Browser environment and proxy settings are
launch metadata only; they do not change Chromium source or implement deep
fingerprint spoofing.

## React product candidate

The daily-use source candidate is available without changing the rollback-safe
root `main.py`. It uses React/Vite/Tailwind in `frontend/`, hosted by pywebview,
with Python `revamped/product_api.py` as the authoritative bridge. Build it with
`npm install` and `npm run build` from `frontend/`, then run
`python -m revamped.product_main`. See [docs/PRODUCT_CANDIDATE.md](docs/PRODUCT_CANDIDATE.md)
for the account, proxy, export, backup, and snapshot behavior.

## M7 environment behavior

- `Desktop` (including older `default` metadata) keeps the normal launch flags.
- `Mobile` applies generic mobile user-agent, touch, viewport, language, and
  device-scale launch settings. The default scale factor is `1.0` and safe
  per-profile overrides remain supported.
- `Custom` accepts validated viewport, scale, language, mobile/touch, and timezone
  metadata. Timezone is stored and validated but is not applied by the launcher
  because the app has no CDP/session layer.
- Invalid optional environment metadata falls back to a normal desktop launch.

## M8 optional proxy behavior

- Proxy configuration is optional and isolated per profile. Proxy Off is the
  default and adds no `--proxy-server` switch.
- Valid unauthenticated `http`, `https`, `socks4`, and `socks5` endpoints are
  normalized and passed to Chromium only for the profile that enabled them.
- Malformed or incomplete optional proxy metadata safely behaves as Proxy Off;
  it does not prevent a profile from launching.
- M8 does not support proxy authentication, credential storage, proxy rotation,
  proxy health checks, or provider integration. Credential-bearing pasted input
  is rejected before save and is never stored in `profiles.json`, logged, or
  passed to Chromium.

## M5 extension behavior

- Account setup deploys only the approved autofill extension using staged
   per-profile copies, then writes only the selected profile's autofill
   `config.js`. The bundled token-extractor source is quarantined and is never
   required, enabled, staged, or launched.
- Other valid extensions in the registry remain available for explicit future
   default policies without adding another hard-coded deployment path.
- Existing profile deployments are compatible across manager restarts. Missing or
  invalid optional deployments are skipped during launch so browser profile data
  remains usable; account setup reports source/deployment errors clearly.
- Source updates replace reusable extension files without sharing account
  configuration between profiles. Extra profile-local extension files are retained.
- Account import continues to create isolated browser roots and isolated extension
  configuration for each imported synthetic account.

## R14 workspace and account boundary

The revamped development composition requires an explicit workspace below the
repository `tmp/` directory and accepts only synthetic `@example.invalid`
account identifiers. Product mode requires a separate explicit `--product-root`
decision (or the `compose_product()` API); it refuses unmarked existing state
and never infers the repository's live `profiles/` or `config/` directories.
Product mode persists only an account label and non-sensitive identifier.
Passwords, tokens, TOTP secrets, sessions, cookies, and equivalent fields are
rejected. The R14 product boundary remains a parallel/dev-only composition;
the root `main.py` and packaging are unchanged and locked.

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
copy-only legacy-to-`profiles/` migration safeguards, application-owned
metadata recovery/atomic-write safeguards, environment presets, and optional
proxy behavior.

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

## Manual acceptance

Use the current source-review checklist in
[`docs/MANUAL_ACCEPTANCE.md`](docs/MANUAL_ACCEPTANCE.md). It separates automated
unit tests, the optional real-Chromium smoke test, visible GUI checks, and
optional real Discord behavior. It also includes disposable-profile instructions,
M7 environment checks, M8 proxy checks, missing-runtime behavior, and migration
safety checks.

Do not treat automated tests as proof of GUI or Discord behavior, and do not start
packaging until the user explicitly approves the source-code version.
