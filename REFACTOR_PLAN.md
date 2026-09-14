# Parallel Revamped Refactor Plan

The legacy implementation remains the golden reference and stable entrypoint.
This plan adds a development-only `revamped/` implementation without changing
`main.py`, packaging, or live user data.

## Milestones

| Milestone | Scope | Gate |
| --- | --- | --- |
| R0 | Capture baseline, freeze rules, and safety boundaries. | `verify.py`, frozen 170-test suite, and protected-source hashes pass. |
| R1 | Add side-effect-free package scaffolding, disposable fixtures, adapters, and freeze checks. | New infrastructure tests pass; legacy remains unchanged. |
| R2 | Implement injected path, identity, timestamp, and model primitives. | Synthetic path/error parity passes. |
| R3 | Implement environment and unauthenticated proxy policy. | Deterministic M7/M8 parity passes; no network or secrets. |
| R4 | Implement application catalog and legacy compatibility storage. | Disposable storage and fault-injection parity passes. |
| R5 | Implement injected process inspection and Chromium command assembly. | Exact synthetic launch parity passes; no real process starts. |
| R6 | Isolate staged extension deployment and legacy account compatibility. | Synthetic M1/M5 behavior and hygiene gates pass. |
| R7 | Implement disposable profile lifecycle and copy-only migration. | Lifecycle, rollback, and recovery gates pass. |
| R8 | Implement headless GUI model/controller and development UI boundary. | Fake-widget M6–M8 behavior passes; no manual claim. |
| R9 | Compose `python -m revamped.main` behind an explicit disposable root. | Safe-startup and composition gates pass; `main.py` stays legacy. |
| R10A | Run the automated parity audit only. | All automated gates pass; manual acceptance remains user-owned. |

Packaging, runtime replacement/updating, secure credential migration, proxy
authentication/rotation, token extraction, anti-detection behavior, and a stable
entrypoint switch are outside this plan.
