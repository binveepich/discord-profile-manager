# Revamped Architecture Target

The additive implementation is organized around meaningful boundaries:

```text
core / models / environment / proxy / processes
                    ↓
                 storage
                    ↓
                 profiles
                 /      \
          extensions   launcher
              ↓           ↓
           accounts       |
                \         /
                    gui
                     ↓
                revamped.main
```

Target modules:

- `core.py`: injected project paths, safety helpers, and error categories.
- `models.py`: immutable/internal records, timestamps, and view records.
- `environment.py` / `proxy.py`: deterministic M7/M8 policy only.
- `processes.py`: injectable Chromium process inspection.
- `storage.py`: application catalog, legacy compatibility state, and atomic
  publication coordination.
- `profiles.py`: profile discovery, lifecycle, layout validation, and migration.
- `extensions.py`: validated staged per-profile extension deployment.
- `accounts.py`: isolated compatibility wrapper for the existing account format.
- `launcher.py`: injected command assembly and process factory.
- `gui.py`: headless-friendly table/controller behavior plus optional Tk wiring.
- `main.py`: development-only composition requiring an explicit disposable root.

`revamped/__init__.py` must be import-safe: no filesystem, logging, Tk, process,
or profile side effects. The stable root `main.py` is not a dependency of this
package and remains the legacy entrypoint until a later human decision.
