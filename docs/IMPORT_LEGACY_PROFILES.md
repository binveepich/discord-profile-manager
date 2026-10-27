# Importing legacy profiles into the revamped app

Written for: the person who runs the import on this machine.

The importer copies legacy Ungoogled Chromium portable profiles into the revamped
state root and registers them in the revamped catalog. It never launches Chromium,
never calls Discord, and never reads or prints passwords, TOTP secrets, tokens, or
proxy passwords. Passwords and TOTP secrets stay inside the copied `config.js`, as they
already were in the legacy profile.

Script: `scripts\import_legacy_profiles.py`

In this guide:

- `<STATE_ROOT>` is the revamped state root. The React app uses the repository folder,
  `<REPO>`, by default. It holds `config\`, `profiles\`, and `data\`.
- `<LEGACY_INSTALL>` is a legacy portable install folder: the folder that contains
  `data\Local State`. In examples, `<LEGACY_SOURCE_1>` and `<LEGACY_SOURCE_2>`
  stand for the user's first and second legacy install roots.

## 1. Prerequisites

1. Close the revamped app and every Chromium window. The importer refuses to run
   while Chromium is using the state root, and it refuses to copy a legacy profile that
   Chromium is using.
2. The state root must already be initialized, meaning `<STATE_ROOT>\config\profiles.json`
   exists. Start the app once against the root if it does not.
3. Free disk space. The dry run prints how much the copy needs. The script also keeps a
   1 GiB margin and refuses to start if the margin would be breached.
4. Back up the state root before the first `--apply`. Copy `config\`, `data\`,
   `legacy\data\`, and `profiles\` to a folder outside the repository. Keep the copy
   somewhere durable; a temporary folder may be cleaned up by the system.
5. Python 3.13 with `psutil` and `pywebview` installed (`requirements.txt`).

Always run from the repository root.

## 2. Options

| Option | Meaning |
|---|---|
| `--root <STATE_ROOT>` | Required. The revamped state root to import into. |
| `--source <LEGACY_INSTALL>` | Required, repeatable. The first listed install wins when one account appears in several. |
| `--apply` | Writes the import. Without it the run is a dry run and writes nothing. |
| `--skip-caches` | Omits regenerable Chromium caches (`Cache`, `Code Cache`, `GPUCache`, `ShaderCache`, and similar). Cookies, Local Storage, IndexedDB, Service Worker, Preferences, and extensions are kept. |
| `--include-orphans` | Also imports folders that exist on disk but are missing from the legacy registry. |
| `--limit N` | Imports at most N new profiles in this run. Already-imported profiles do not count. |
| `--report <file>` | Writes a JSON report. A dry run writes it only when this option is given. An apply always writes `logs\legacy-import\<stamp>\report.json`. |

## 3. Dry run (writes nothing)

```powershell
cd <REPO>
python -B scripts\import_legacy_profiles.py `
  --root "<REPO>" `
  --source "<LEGACY_SOURCE_1>\ungoogled-chromium-portable" `
  --source "<LEGACY_SOURCE_2>\ungoogled-chromium-portable" `
  --skip-caches --include-orphans `
  --report "logs\legacy-import\dry-run.json"
```

The output lists the source counts, how many profiles would be imported, the copy size,
each planned copy (legacy folder, the new `profile_NNNN` id, and a masked account), and
every skipped profile with its reason. Exit code `0` means the plan is clean. Exit code
`2` means there are blockers, and `--apply` will refuse to run.

## 4. Test with a few profiles, then the full batch

Test first with a small batch:

```powershell
python -B scripts\import_legacy_profiles.py --root "<REPO>" `
  --source "<LEGACY_SOURCE_1>\ungoogled-chromium-portable" `
  --source "<LEGACY_SOURCE_2>\ungoogled-chromium-portable" `
  --skip-caches --include-orphans --limit 3 --apply
```

Then confirm the app lists them (section 5). Then run the full batch with the same
options minus `--limit`:

```powershell
python -B scripts\import_legacy_profiles.py --root "<REPO>" `
  --source "<LEGACY_SOURCE_1>\ungoogled-chromium-portable" `
  --source "<LEGACY_SOURCE_2>\ungoogled-chromium-portable" `
  --skip-caches --include-orphans --apply
```

Re-running is safe. Profiles already in the ledger, and accounts already in the catalog,
are skipped. `--limit` counts only new imports, so `--limit 3` run twice imports six
profiles, not the same three.

## 5. Verify the result

1. The apply output ends with `Verification: catalog=N listed_by_app=N expected=N`.
   All three numbers should match. Any `PROBLEM` line needs attention before you use the data.
2. Ask the app itself for its count, without opening a window. Set UTF-8 output first,
   because the Vietnamese product name cannot be written to a cp1252 pipe:

   ```powershell
   $env:PYTHONIOENCODING = "utf-8"
   python -B -m revamped.product_main --no-gui --root "<REPO>"
   ```

   It prints `Profiles: N`. This startup path does not launch Chromium.
3. Open the report at `logs\legacy-import\<stamp>\report.json`. It holds masked accounts
   and reasons only. Passwords and TOTP secrets never appear in it.
4. The ledger `config\legacy_import_ledger.json` lists one entry per imported profile
   (legacy source, legacy folder, new profile id). The app ignores this file. The script
   uses it to skip profiles that were already imported.

Do not launch imported profiles to test them until you have decided how to handle the
token-extractor folder (section 7).

## 6. Field mapping (legacy to revamped)

| Legacy (portable install) | Revamped | Notes |
|---|---|---|
| `data\Local State` `profile.info_cache["Profile N"]` | one record in `config\profiles.json` `profiles[]` | Only the fields below are copied. |
| folder name `Profile N` | `profile_id` = next free `profile_NNNN` | Legacy names are not valid managed ids. The legacy folder is kept in the ledger. |
| `name` | `display_name` | Trimmed. Falls back to the folder name when empty. |
| `created` (epoch seconds) | `created_at` (UTC) | Falls back to the import time when missing. |
| (not recorded) | `last_opened_at` = null | The legacy manager does not record it. |
| `avatar_icon` | not mapped | No equivalent in the revamped app. |
| `Unpacked Extensions\discord-autofill-extension\config.js` `email` | `account` = `{mode: product, email}` | The only account data kept in `profiles.json`. |
| same file `password`, `totpSecret` | not mapped | Stay inside the copied `config.js`. Never written to `profiles.json`, logs, or reports. |
| `Unpacked Extensions\discord-token-extractor-extension` | copied as-is | Not recorded in `profiles.json`. See section 7. |
| `Preferences`, `Default\`, `Local State`, other Chromium data | copied as-is into `profiles\profile_NNNN\` | Cookies, storage, and IndexedDB are kept. |
| `Default\Cache`, `Code Cache`, `GPUCache`, `ShaderCache`, and similar | omitted with `--skip-caches` | Chromium rebuilds them. |
| no proxy setting in legacy | `proxy_enabled` = false | The portable manager has no proxy settings. |
| no environment setting in legacy | default environment preset | The portable manager has no environment settings. |
| orphan folder (on disk, not in the registry) | imported only with `--include-orphans`, named after the folder | Orphans with no usable email are imported without an account. |

Legacy fields with no revamped equivalent: `avatar_icon`, and the legacy registry format
itself. Proxy and environment data do not exist in the portable install, so nothing is
lost there. Chromium caches are dropped only when `--skip-caches` is used.

## 7. Known issues to decide before launching imported profiles

- Imported profiles may already contain the optional `discord-token-extractor-extension`.
  Valid existing copies are preserved and may load; fresh profiles do not receive it by
  default. Its source remains in the repository but is excluded from release builds.
  Review an imported profile's extension state before launch if you do not want it enabled.
- The autofill extension fills Discord's login form with each profile's stored email,
  password, and TOTP when a profile opens on discord.com.

## 8. Roll back

Close the revamped app and Chromium first.

**Option A: remove a few profiles.** Delete the imported profiles inside the app using its
normal Delete action. The app's delete flow handles the catalog, the mirror, and the folders.
Your legacy sources are not touched.

**Option B: restore the state before a run.** Each apply run saves its pre-run metadata in
`logs\legacy-import\<stamp>\before\`. To undo every import from the first run, use the
first run's folder:

1. Copy these files back from `before\` to the same paths under `<STATE_ROOT>`:
   `config\profiles.json`, `data\Local State`, and `legacy\data\Local State`.
2. If `before\config\legacy_import_ledger.json` exists, copy it back. If it does not, delete
   `config\legacy_import_ledger.json`.
3. Move every imported folder out of `profiles\` into a quarantine folder that you keep.
   Do not delete them. The ledger lists each `profile_id` that was imported.
4. Run `python -B -m revamped.product_main --no-gui --root <STATE_ROOT>` (with
   `PYTHONIOENCODING=utf-8`) and confirm the count returns to the pre-import number.

Option B also reverts changes the app made after that run, such as profile open times and
UI preferences. Restore `config\ui_preferences.json` from `before\` only if you want that.
Use the backup you made in section 1 if you need a full rollback to an earlier point.

## 9. Common errors

| Message | Cause | Fix |
|---|---|---|
| `... is not an initialized revamped state root` | `config\profiles.json` is missing. | Start the app once against this root, or fix `--root`. |
| `... is not a legacy install (data\Local State is missing)` | `--source` points at the wrong folder. | Point it at the folder that contains `data\`. |
| `disk space: the copy needs ...` | Not enough free space on the state root's drive. | Use `--skip-caches`, free space, or choose another `--root`. |
| `Chromium is using the revamped data or profiles root` | A browser window is open. | Close the revamped app and its Chromium windows. |
| `Chromium is running on this profile; close it first` | That legacy profile is open in a browser. | Close it, or leave it out. The rest still imports. |
| `same account as ... (first listed install wins)` | The account appears in an earlier `--source` install. | Expected. Change the source order if you want the other copy. |
| `already in the revamped catalog (duplicate)` | The account is already registered. | Expected. Nothing is changed. |
| `orphan folder: not in the legacy registry` | The folder is missing from the legacy registry. | Add `--include-orphans` to import it. |
| `contains links or junctions; not copied` | The legacy profile has a link. | Not copied. Recreate the profile in the app, or inspect the link. |
| `no Chromium Preferences file` / `browser data sits in the profile root` / `last_used folder is missing` | The folder is not a layout the app can open. | Skipped on purpose. The report gives the reason. |
| `Application profile metadata changed during this operation` (`Published: False`) | The app changed the catalog while the import ran. | Nothing was registered. Copies were moved to `profiles\.import-partial-*`. Check them, then move or delete them. Re-run the import. |
| `.import-partial-profile_NNNN-<stamp>` folders | A copy failed midway. | They start with a dot, so the app does not register them. Move them out of `profiles\`. |
| `UnicodeEncodeError` with `--no-gui` | The console or pipe is not UTF-8. | Set `$env:PYTHONIOENCODING = "utf-8"` first. |
| `legacy import ledger is unreadable` | `config\legacy_import_ledger.json` is damaged. | Fix or move it. Nothing was changed. |
| `Cannot check whether Chromium is using the legacy profiles` | The process check failed. | Retry. The import refuses to run without that check. |
| `config.js has no email field; imported without an account` | The autofill config has no usable email. | Expected. The profile is imported without an account. |

## 10. What the script never does

- It never deletes anything. Partial copies are moved aside, and rollback moves folders.
- It never writes to a legacy install. The source is read only.
- It never launches Chromium or the autofill extension, and it never calls Discord.
- It never writes passwords, TOTP secrets, tokens, or proxy passwords into the catalog,
  logs, or reports.
