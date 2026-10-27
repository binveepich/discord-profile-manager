# Manual Acceptance Checklist — Source App Review

## Purpose

Use this checklist before approving packaging.

Passing the automated structural checks is required, but it does not prove the visible GUI and real browser behavior are manually approved.

## Safety rules

Use only disposable profiles and synthetic accounts.

Do not use production credentials.

Do not delete or modify real working profiles while testing.

Close disposable Chromium windows before deletion tests.

## 1. Automated structural checks

Run:

```powershell
python -B scripts/verify.py
```

Record result:

```text
Automated structural checks:
PASS / FAIL
Notes:
```

These checks read source files and file presence only. They do not run the app,
open a window, or start Chromium, so they do not prove visible GUI behavior
or real Discord behavior.

## 2. Manual GUI checks

The sections below require a visible manager and browser. Record a result only
after performing the check yourself; automated checks are not GUI
evidence.

### Startup

1. From project root, run:

```powershell
python -B main.py --legacy
```

2. Confirm the manager window opens.
3. Confirm existing profiles appear.
4. Close and restart once.

Record:

```text
Startup:
PASS / FAIL
Notes:
```

### Legacy command compatibility

Run:

```powershell
python -B .\legacy\profile_manager.py
```

Confirm it launches the same app.

Record:

```text
Legacy command:
PASS / FAIL
Notes:
```

### Create and open disposable profiles

1. Create `Manual Test A`.
2. Create `Manual Test B`.
3. Decline account setup if asked.
4. Open only `Manual Test A`.
5. Visit `chrome://version`.
6. Confirm executable path ends with `browser\chrome.exe`.
7. Confirm profile path belongs to a distinct `profiles\profile_####` root.

Record:

```text
Create/open:
PASS / FAIL
Profile A ID/path:
Notes:
```

### Isolation

1. In `Manual Test A`, create a harmless bookmark named `Manual A Marker`.
2. Open `Manual Test B`.
3. Visit `chrome://version` in B.
4. Confirm B uses a different profile path.
5. Confirm B does not have A's bookmark.

Record:

```text
Profile isolation:
PASS / FAIL
Notes:
```

### Rename and restart

1. Close A and B browser windows.
2. Rename `Manual Test A` to `Manual Test A Renamed`.
3. Restart the manager.
4. Open the renamed profile.
5. Confirm the profile path and bookmark survived.

Record:

```text
Rename/restart:
PASS / FAIL
Notes:
```

### Multi-open and running state

1. Select A and B together.
2. Open both.
3. Confirm two distinct browser profile paths.
4. Try opening both again.
5. Confirm running profiles are detected or skipped rather than duplicated.

Record:

```text
Multi-open/running state:
PASS / FAIL
Notes:
```

### Synthetic account import

Create a synthetic account file:

```powershell
New-Item -ItemType Directory -Path .\tmp -Force | Out-Null
@'
manual-one@example.invalid:synthetic-password-one
manual-two@example.invalid:synthetic-password-two
'@ | Set-Content -LiteralPath .\tmp\manual-accounts.txt -Encoding ASCII
```

1. Import TXT.
2. Confirm two profiles are created.
3. Use View Account to confirm only synthetic email identifiers.
4. Restart the manager and confirm they remain assigned.

Do not submit credentials to Discord.

Record:

```text
Synthetic import:
PASS / FAIL
Notes:
```

### Extension loading

1. Open one imported synthetic test profile.
2. Visit `chrome://extensions`.
3. Confirm Discord Autofill is loaded.
4. Confirm the extension deployment is profile-local and the other imported
   profile has its own deployment.

Record:

```text
Extension loading:
PASS / FAIL
Notes:
```

### Environment presets

Check with disposable profiles only.

### Desktop

1. Set profile environment to Desktop/default.
2. Launch profile.
3. Confirm normal launch without mobile-only arguments in `chrome://version`.

### Mobile

1. Set profile environment to Mobile.
2. Launch profile.
3. Confirm mobile-related flags/viewport behavior are visible enough for manual
   review. The current default device scale factor is `1.0`; custom overrides
   remain user-configurable.

### Custom

1. Set custom width/height/language/touch/mobile fields.
2. Launch profile.
3. Confirm no crash and inspect the resulting launch behavior where possible.
   Timezone is stored/validated but is not applied by the current launcher.

Record:

```text
Environment presets:
Desktop: PASS / FAIL
Mobile: PASS / FAIL
Custom: PASS / FAIL
Notes:
```

### Proxy M8 checks

Use disposable profiles only.

### Proxy OFF

1. Confirm a profile with proxy disabled launches normally.
2. Confirm no proxy behavior is forced.

### Invalid proxy

1. Enter invalid proxy metadata.
2. Confirm the app reports or safely falls back.
3. Confirm the profile does not become unlaunchable.

### Valid unauthenticated proxy

1. Enter a syntactically valid unauthenticated endpoint.
2. Confirm it is saved/displayed as expected.
3. Launch the profile and inspect `chrome://version` if available to confirm
   only that profile's `--proxy-server` switch is present.
4. Treat this as syntax/launch-switch validation, not a reachability test. Do
   not test production accounts through unknown proxies.

### Proxy authentication boundary

1. Paste a credential-bearing proxy string into the proxy editor.
2. Confirm the UI explains that authenticated proxy launch/storage is not
   supported in M8.
3. Confirm Save does not accept it. Do not place proxy credentials in files,
   screenshots, notes, or bug reports.

Record:

```text
Proxy OFF:
PASS / FAIL

Invalid proxy fallback:
PASS / FAIL

Valid unauthenticated proxy:
PASS / FAIL

Notes:
```

### Delete disposable profiles

1. Close disposable browser windows.
2. Select only a disposable profile.
3. Click Delete and cancel first.
4. Confirm it remains.
5. Repeat and confirm deletion.
6. Restart manager and confirm deleted profile is gone.
7. Confirm unrelated profiles remain.

Record:

```text
Deletion:
PASS / FAIL
Notes:
```

### Different working directory

Close manager and run:

```powershell
Set-Location -LiteralPath '<REPO>\config'
python -B '..\main.py' --legacy
```

If `..\main.py` does not resolve from that location, run the compatible legacy command:

```powershell
python -B '..\legacy\profile_manager.py'
```

Confirm profiles and browser runtime still resolve correctly.

Record:

```text
Different working directory:
PASS / FAIL
Notes:
```

### Missing runtime behavior

Use a disposable script-only copy. Do not rename or remove the real `browser/`.

Record:

```text
Missing runtime:
PASS / FAIL / SKIPPED
Notes:
```

## 3. Real Discord behavior (separate, optional)

Automated checks and GUI checks do not verify Discord
login, autofill, or TOTP behavior. If this is tested manually, use only a
dedicated non-production test account that the user has explicitly approved;
never use production credentials. A safe minimum is:

1. Use one disposable profile and open Discord's login page.
2. Confirm the intended synthetic/test email fields appear in that profile only.
3. Do not submit `example.invalid` synthetic credentials or any unapproved
   credentials.
4. Record the result separately from extension loading and GUI results.

Record:

```text
Real Discord behavior:
PASS / FAIL / NOT TESTED
Notes:
```

This document does not claim that GUI or Discord behavior has been verified.

## 4. Final manual decision

```text
Source app approved for packaging?
YES / NO

If NO, required fixes:
- 
- 
- 
```

Do not start packaging until the user explicitly approves it.
