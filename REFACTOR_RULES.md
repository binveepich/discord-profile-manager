# Parallel Refactor Rules

1. `legacy/profile_manager.py`, `main.py`, and the existing M1–M8 tests are
   frozen golden reference files. Never edit, reformat, redirect, or rename them.
2. Never read, print, migrate, repair, delete, or overwrite live `profiles/`,
   `browser/`, `config/profiles.json`, `legacy/data/`, `legacy/log/`, or existing
   profile-local extension deployments.
3. All new stateful tests use disposable roots under `tmp/` and synthetic
   `example.invalid` accounts. Chromium process creation is injected or mocked.
4. New stateful code must receive explicit paths. It must not silently fall back
   to the project’s live directories.
5. Prefer standard-library code and small meaningful modules. Do not add features
   unrelated to architectural parity.
6. Preserve Windows path semantics, reparse-point rejection, fail-closed process
   checks, atomic writes, stale-write detection, and failure-path data safety.
7. Keep account compatibility isolated. Do not redesign or migrate plaintext
   account storage during this refactor, and never log credential values.
8. Do not switch the stable entrypoint, package the app, launch real Chromium, or
   perform manual GUI/Discord acceptance as part of autonomous work.
9. Stage explicit files only. Never use broad Git staging, cleanup, reset, or
   history-rewrite commands.
10. A milestone is complete only after its stated gate and the frozen legacy gate
    pass; record failures and limitations instead of hiding them.
