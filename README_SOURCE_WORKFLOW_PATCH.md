# README source workflow patch

Suggested README update. Merge this into `README.md` after M9/M10 are implemented.

---

## Preferred source run command

From the project root:

```powershell
python -B main.py
```

Compatibility command:

```powershell
python -B .\legacy\profile_manager.py
```

`main.py` is a thin root-level entrypoint. The current implementation remains in `legacy/profile_manager.py` until a separate, tested refactor is approved.

## Verification

Run the full verification workflow:

```powershell
python -B scripts/verify.py
```

Or run the unit suite directly:

```powershell
python -B -m unittest discover -s tests -v
```

Unit tests use synthetic data and must not access production Discord accounts or real profile credentials.

## Packaging status

Packaging is not active yet.

Do not build `.exe`, installer, or GitHub release artifacts until the user manually approves the source-code version.

Current goal:

- source app works
- source app is testable
- source app has a clear entrypoint
- manual acceptance checklist is complete
- existing profile data is preserved
