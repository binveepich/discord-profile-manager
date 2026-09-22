# AGENTS.md append section — Packaging lock and autonomous source workflow

Add this section to the existing `AGENTS.md`. Do not replace the whole file unless the user explicitly requests it.

---

## Current packaging lock

Windows packaging is locked until the user explicitly approves the source-code version.

Do not implement any of the following unless the user explicitly asks for packaging after manual acceptance:

- `.exe` generation
- Manager.exe
- PyInstaller setup
- Nuitka setup
- cx_Freeze setup
- installer scripts
- GitHub release upload
- automatic update packaging
- browser runtime updater
- browser runtime rollback workflow

Current priority:

1. preserve existing working behavior
2. close current source-code milestones
3. keep the app runnable from source
4. make verification easy
5. make manual review easy

## Autonomous source workflow

When working autonomously:

1. Read `AGENTS.md`, `REQUIREMENTS.md`, `CODEX_HANDOFF.md`, and `CODEX_PLAN.md`.
2. Inspect `git status`.
3. Run the current verification command or full unit suite before editing.
4. Work on only the first incomplete unlocked milestone.
5. Make small, testable changes.
6. Run targeted tests after edits.
7. Run the full unit suite before marking a milestone complete.
8. Update `CODEX_STATUS.md`.
9. Commit each completed milestone separately.
10. Stop before any packaging, installer, release, destructive migration, or real-data operation.

Do not stop merely because the first implementation approach fails. Diagnose, fix, retest, and continue within the safe unlocked scope.
