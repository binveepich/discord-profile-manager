# Discord Profile Manager — Codex Autonomous Plan

## User decision

Packaging is LOCKED.

Do not build `.exe`, installer, PyInstaller/Nuitka/cx_Freeze config, GitHub release upload, or Windows distribution workflow until the user explicitly says the source-code version is approved for packaging.

The current goal is a stable source-code application that can be run, tested, and manually reviewed before packaging.

## Immediate target

Create a stable source-code release candidate:

- M8 proxy milestone closed
- M1-M7 behavior preserved
- clear root-level source entrypoint
- clear verification command
- current manual acceptance checklist
- no destructive profile/runtime changes
- no packaging

## Mandatory baseline

Current implementation entry:

```powershell
python -B .\legacy\profile_manager.py
```

Preferred source entry after M9:

```powershell
python -B main.py
```

Current mandatory unit test gate:

```powershell
python -B -m unittest discover -s tests -v
```

Optional diagnostic smoke test:

```powershell
python -B tests/browser_smoke_m2.py
```

The smoke test is diagnostic only. A smoke failure must not automatically be treated as proof that normal visible GUI launch is broken.

## Global rules

Before any change:

1. Read `AGENTS.md`.
2. Read `REQUIREMENTS.md`.
3. Read `CODEX_HANDOFF.md`.
4. Inspect `git status`.
5. Run the mandatory unit test gate.
6. Preserve all user-owned working-tree changes.
7. Never reset, checkout, discard, or delete local work unless explicitly instructed by the user.

During work:

1. Work on the first incomplete unlocked milestone only.
2. Make small, testable changes.
3. Run targeted checks after edits.
4. Run the full unit suite before marking a milestone complete.
5. Update `CODEX_STATUS.md`.
6. Commit each completed milestone separately.
7. Do not move to the next milestone if the regression gate fails.

Never touch or dump:

- real `profiles/` data
- real account configs
- raw `config/profiles.json`
- raw `legacy/data/Local State`
- raw logs
- credentials
- tokens
- TOTP secrets
- browser session data
- browser runtime files under `browser/`

unless the user explicitly requests a safe, scoped operation.

---

## M8-CLOSE — Optional proxy milestone

Status: COMPLETE

### Objective

Finalize the current optional unauthenticated per-profile proxy feature.

### Scope

Allowed:

- review existing M8 proxy code
- review `tests/test_m8_proxy.py`
- update docs/status for M8
- fix M8 regressions
- confirm proxy-off fallback behavior
- confirm credentials are not stored, logged, or launched

Not allowed:

- proxy authentication
- proxy rotation
- proxy provider integration
- proxy health checking
- storing proxy usernames/passwords
- passing proxy credentials to Chromium

### Acceptance criteria

- [x] Current M8 working-tree changes are preserved.
- [x] Proxy is optional per profile.
- [x] Proxy OFF profiles launch without `--proxy-server`.
- [x] Valid unauthenticated HTTP/HTTPS/SOCKS4/SOCKS5 endpoint metadata is accepted.
- [x] Invalid optional proxy metadata falls back safely.
- [x] Proxy credentials are not stored in `profiles.json`.
- [x] Proxy credentials are not logged.
- [x] Proxy credentials are not passed to Chromium.
- [x] M1-M7 behavior remains compatible.
- [x] Full unit test suite passes (170 tests).
- [x] Documentation/status explains current M8 behavior.
- [x] M8 is committed separately.

---

## M9 — Source app stability

Status: COMPLETE

### Objective

Make the app easier to run and review from source before packaging.

### Scope

Allowed:

- add root-level `main.py` as a thin wrapper
- keep `legacy/profile_manager.py` as the implementation entrypoint
- update README/source-run docs
- avoid architectural refactor

Expected `main.py`:

```python
from legacy.profile_manager import main

if __name__ == "__main__":
    main()
```

### Acceptance criteria

- [x] Root-level `main.py` exists, or an equivalent clear source entry is documented.
- [x] `python -B main.py` delegates to the same application behavior.
- [x] `python -B .\legacy\profile_manager.py` remains compatible.
- [x] README documents the preferred source-run command.
- [x] No broad refactor is performed.
- [x] Full unit test suite passes (170 tests).
- [x] M9 is committed separately.

---

## M10 — Verification workflow

Status: COMPLETE

### Objective

Create one simple verification command for future Codex sessions.

### Scope

Allowed:

- add `scripts/verify.py`
- run syntax checks
- run unit tests
- print safe PASS/FAIL summary
- check only structural runtime presence

Not allowed:

- printing raw account/profile/log/config contents
- reading production credentials
- launching real Discord
- modifying user data

### Expected command

```powershell
python -B scripts/verify.py
```

### Expected output shape

```text
SYNTAX: PASS
UNIT TESTS: PASS
ENTRYPOINT: PASS
RUNTIME STRUCTURE: PASS
AUTONOMOUS GATE: PASS
```

### Acceptance criteria

- [x] `scripts/verify.py` exists.
- [x] Syntax check is included.
- [x] Unit test discovery is included.
- [x] PASS/FAIL summary is clear.
- [x] Script does not print credentials, raw logs, raw account config, raw metadata, or profile contents.
- [x] Script returns a non-zero exit code on failure.
- [x] Full unit test suite passes (170 tests).
- [x] M10 is committed separately.

---

## M11 — Manual acceptance documentation

Status: TODO

### Objective

Create a current manual checklist for user review before packaging.

### Scope

Allowed:

- create/update `docs/MANUAL_ACCEPTANCE.md`
- convert README checklist into a cleaner current-app checklist
- add M7 environment checks
- add M8 proxy checks
- require disposable profiles
- separate automated tests, smoke tests, GUI checks, and real Discord behavior

Not allowed:

- claiming manual verification that was not performed
- using real credentials
- damaging real profile data

### Acceptance criteria

- [ ] `docs/MANUAL_ACCEPTANCE.md` exists.
- [ ] Checklist uses disposable profiles.
- [ ] Startup/create/open/isolation/rename/delete/import checks are included.
- [ ] M7 environment checks are included.
- [ ] M8 proxy checks are included.
- [ ] Automated unit tests, optional smoke tests, manual GUI checks, and Discord behavior are clearly separated.
- [ ] Docs do not claim unperformed manual verification.
- [ ] Full unit test suite passes.
- [ ] M11 is committed separately.

---

## M12 — Packaging

Status: LOCKED

Do not start.

Out of scope until explicit user approval:

- Manager.exe
- installer
- portable release packaging
- PyInstaller
- Nuitka
- cx_Freeze
- GitHub release upload
- browser runtime updater
- automatic update/rollback workflow

User approval phrase example:

```text
Now start packaging milestone.
```

Only after that phrase or an equivalent explicit instruction may Codex start packaging work.
