# Discord Profile Manager — Codex Status

## Current user decision

Packaging is LOCKED.

The user wants the source-code app to feel complete and manually approved before any `.exe`, installer, or GitHub release packaging work begins.

## Current source status

Known from handoff:

- Current branch: `main`
- Current HEAD before M8 close: `24f7716 M7: add per-profile browser environment presets`
- M1-M6: completed/inferred or committed baseline
- M7: committed, with local mobile DPR adjustment
- M8: implemented in working tree, not yet committed at handoff time
- M9+: not started at handoff time

## Mandatory test gate

```powershell
python -B -m unittest discover -s tests -v
```

Handoff observed:

```text
PASS — 170 tests, OK
```

Do not mark any milestone complete unless the current full unit suite passes.

## Optional diagnostic smoke

```powershell
python -B tests/browser_smoke_m2.py
```

This is diagnostic only. A failure here must be reported separately from unit tests and must not cause production launcher changes unless the root cause is clearly understood.

## Milestones

### M8-CLOSE — Optional proxy milestone

Status: COMPLETE

Required before completion:

- [x] review current M8 proxy implementation
- [x] review M8 tests
- [x] confirm no proxy credentials stored/logged/launched
- [x] confirm proxy-off fallback
- [x] full unit suite PASS (170 tests)
- [x] docs/status updated
- [x] commit created

### M9 — Source app stability

Status: COMPLETE

Required before completion:

- [x] root-level source entrypoint created or confirmed
- [x] `python -B main.py` delegates to the existing implementation
- [x] legacy command remains compatible
- [x] README updated
- [x] full unit suite PASS (170 tests)
- [x] commit created

### M10 — Verification workflow

Status: COMPLETE

Required before completion:

- [x] `scripts/verify.py` exists
- [x] syntax check included
- [x] unit test runner included
- [x] safe PASS/FAIL summary
- [x] full unit suite PASS (170 tests)
- [x] commit created

### M11 — Manual acceptance documentation

Status: COMPLETE

Required before completion:

- [x] `docs/MANUAL_ACCEPTANCE.md` exists
- [x] disposable profile checklist included
- [x] M7 environment checks included
- [x] M8 proxy checks included
- [x] automated/smoke/manual/Discord checks separated
- [x] full unit suite PASS (170 tests)
- [x] commit created

### M12 — Packaging

Status: LOCKED

Do not start until explicit user approval.

## Final report template

When stopping, report:

```text
Current git status:
Commits created:
Milestones completed:
Files changed:
Tests run:
Test results:
Manual checks still required:
Known limitations:
Blockers:
```
