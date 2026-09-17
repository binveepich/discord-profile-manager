# Risk Boundaries for Autonomous Codex Work

## Safe autonomous work

Codex may continue without asking when doing:

- documentation updates
- source-run entrypoint wrapper
- verification script
- unit-test improvements using synthetic data
- README/status updates
- small bug fixes with clear tests
- M8 proxy closeout within unauthenticated scope
- non-destructive diagnostics
- small maintainability improvements that preserve behavior

## Human checkpoint required

Codex must stop and report before doing:

- Windows packaging
- Manager.exe generation
- installer creation
- GitHub release upload
- browser runtime updater
- browser runtime replacement
- destructive migration
- deleting or rewriting real profiles
- changing account credential storage against live data
- broad modularization/refactor
- adding anti-detection/fingerprint spoofing
- adding token extraction
- adding proxy credential storage
- using production credentials
- printing raw logs/config/profile/account files

## Absolute preservation rules

Do not delete:

- `profiles/`
- `browser/`
- `config/`
- `extensions/`
- `legacy/data/`
- `legacy/log/`

Do not print or commit:

- passwords
- tokens
- TOTP secrets
- cookies
- session data
- raw account config
- raw browser profile files

## Stop conditions

Stop only if:

- full baseline tests cannot be restored
- production credentials are required
- real profile/browser runtime data would need to be touched
- destructive migration is required
- a product decision is required
- packaging boundary is reached
- environment/usage prevents further execution

Do not stop merely because:

- first implementation approach failed
- tests failed once
- lint/syntax failed once
- a minor bug was found

Instead:

```text
diagnose → fix → retest → continue
```
