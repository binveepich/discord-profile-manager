# Product candidate

The daily-use candidate is a React/Vite/Tailwind interface hosted by
pywebview. Python remains authoritative:

`React UI -> pywebview ProductAPI -> revamped services -> profiles/config/browser`

Install the Python dependencies once with `python -m pip install -r requirements.txt`,
then build and run from PowerShell:

```powershell
Set-Location -LiteralPath '<REPO>\frontend'
npm ci
npm run build
Set-Location -LiteralPath '<REPO>'
python -B main.py
```

`python -B main.py` is the default entrypoint and starts this product. If
`frontend/dist/index.html` is missing, it stops with the build steps instead of
opening a window. `python -m revamped.product_main` starts the same product
directly. The legacy app remains available with `python -B main.py --legacy`.

The candidate uses this checkout's `profiles/`, `config/`, `extensions/`, and
`logs/` directories. It never copies or scans live browser profile contents for
export. Automated tests use disposable roots.

## Accounts and Autofill

The Account tab and TXT importer accept `email:password:2fa` (the `:2fa`
part is optional). Every managed profile gets an independent staged copy of
`extensions/discord-autofill-extension/`; the master source is never written
with an account. The staged profile-local `config.js` contains plaintext
credentials for this v1 compatibility workflow and should be treated as
sensitive local data. Passwords and TOTP secrets are omitted from the catalog,
table, logs, and JSON/CSV exports.

## Profiles, proxy, and environment

STT is a computed four-digit display sequence based on catalog creation/import
order. It compacts after deletion, while profile IDs, directories, and
Chromium data remain stable. Sorting and filtering never rewrite that order.

Every product launch tiles its window by STT: odd STT opens on the left half of
the Windows work area and even STT on the right half. The side is read from the
current STT when the profile opens, so after a deletion the profiles behind it
open on their new side. Windows that are already open are not moved.

Proxy is optional; an empty value means direct connection. Common endpoint
formats can be parsed. Authenticated values are refused: proxy checks and saves accept only
unauthenticated endpoints, and credentials are never stored in application
metadata in this candidate. Proxy checks run in
worker jobs and report Alive/Dead, latency, outbound IP, and best-effort
geography.

Desktop and Mobile use ordinary Chromium-supported runtime settings. Timezone
and hardware categories are metadata-only where Chromium cannot apply them;
the app does not implement deep fingerprint spoofing.

## Snapshot and backup

`scripts/build_final_snapshot.py` is a regeneration tool only. It copies an
allowlist of source modules, the built frontend, and the required master
Autofill source. It never copies profiles, cookies, browser sessions,
`config/profiles.json`, logs, token-extractor material, archive files, or
stored account credentials. Chromium can be included with
`--include-browser` when producing a local source snapshot.

Back up `profiles/` and `config/` before changing browser/runtime files. Profile
deletion is deliberate and is not part of application update behavior.
