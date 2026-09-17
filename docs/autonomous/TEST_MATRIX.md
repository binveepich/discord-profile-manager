# Autonomous Test Matrix

## Mandatory gate

Command:

```powershell
python -B -m unittest discover -s tests -v
```

Requirement:

- Must pass before a milestone can be marked complete.
- Must pass before a commit is created for a completed milestone.
- Must be rerun after fixes.

## Syntax gate

Recommended:

```powershell
python -B -c "from pathlib import Path; paths=[Path('legacy/profile_manager.py'), *Path('tests').glob('*.py')]; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in paths]; print('syntax: OK', len(paths), 'files')"
```

Or use:

```powershell
python -B scripts/verify.py
```

after M10 exists.

## Optional smoke

Command:

```powershell
python -B tests/browser_smoke_m2.py
```

Use as diagnostic only.

Do not weaken production launcher behavior just to make smoke pass unless the root cause is understood and tests/manual checks support the change.

## Manual gates

Required before packaging:

- startup
- create/open
- profile isolation
- rename/restart
- multi-open
- synthetic account import
- extension loading
- delete disposable profile
- environment presets
- proxy checks
- missing runtime behavior
- alternate working directory

## Evidence separation

Always report separately:

```text
Automated unit tests:
Syntax checks:
Smoke test:
Manual GUI checks:
Real Discord behavior:
```

Never claim GUI or Discord behavior is verified based only on unit tests.
