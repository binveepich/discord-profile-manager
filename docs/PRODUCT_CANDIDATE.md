# Product candidate

The daily-use candidate is a React/Vite/Tailwind interface hosted by
pywebview. Python remains authoritative:

`React UI -> pywebview ProductAPI -> revamped services -> profiles/config/browser`

Build and run from PowerShell:

```powershell
Set-Location -LiteralPath 'I:\Discord_Profile_Manager\frontend'
npm install
npm run build
Set-Location -LiteralPath 'I:\Discord_Profile_Manager'
python -m revamped.product_main
```

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

Proxy is optional; an empty value means direct connection. Common endpoint
formats can be parsed. Authenticated values can be diagnosed transiently but
are not stored in application metadata in this candidate. Proxy checks run in
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
