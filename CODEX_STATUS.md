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

Status: TODO

Required before completion:

- [ ] root-level source entrypoint created or confirmed
- [ ] `python -B main.py` works
- [ ] legacy command remains compatible
- [ ] README updated
- [ ] full unit suite PASS
- [ ] commit created

### M10 — Verification workflow

Status: TODO

Required before completion:

- [ ] `scripts/verify.py` exists
- [ ] syntax check included
- [ ] unit test runner included
- [ ] safe PASS/FAIL summary
- [ ] full unit suite PASS
- [ ] commit created

### M11 — Manual acceptance documentation

Status: TODO

Required before completion:

- [ ] `docs/MANUAL_ACCEPTANCE.md` exists
- [ ] disposable profile checklist included
- [ ] M7 environment checks included
- [ ] M8 proxy checks included
- [ ] automated/smoke/manual/Discord checks separated
- [ ] full unit suite PASS
- [ ] commit created

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
