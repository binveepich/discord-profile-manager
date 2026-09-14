# Refactor Status

## Current status

R0 through R9 are complete on the isolated branch `refactor/revamped-parallel`.
R10A is in progress. The stable entrypoint remains legacy and packaging remains locked.

## Milestones

| Milestone | Status | Evidence / next action |
| --- | --- | --- |
| R0 | COMPLETE | Baseline frozen; `verify.py` PASS; frozen suite 170/170; see `docs/refactor/BASELINE.md`. |
| R1 | COMPLETE | Commit `R1: add parallel refactor contract infrastructure`; 5 R1 tests, frozen suite 170/170, and integrity check PASS. |
| R2 | COMPLETE | Core/path/model primitives and deterministic parity committed; 186-test full suite and integrity gate PASS. One symlink test is skipped because the host disallows symlink creation. |
| R3 | COMPLETE | Environment/proxy policy and deterministic parity committed; R3 tests, frozen 170-test suite, and integrity gate PASS. |
| R4 | COMPLETE | Catalog/legacy storage boundaries, locks, atomic writes, stale-write detection, and mirror restore committed; R4 tests, frozen 170-test suite, verify, and integrity PASS. |
| R5 | COMPLETE | Injected process inspection, deterministic launcher assembly, launch failure handling, and launch parity committed; full 207-test suite, verify, compare, and integrity PASS. |
| R6 | COMPLETE | Extension source validation, staged deployment, account compatibility, secret-free logging, and R6 tests pass. |
| R7 | COMPLETE | Disposable-root create/rename/delete/migration/recovery service and 14 lifecycle tests pass; lifecycle parity is PASS. |
| R8 | COMPLETE | Headless cached table model, stable-ID selection, status polling, action controller, safe editor orchestration, and Tk rendering adapter pass 9 R8 tests. |
| R9 | COMPLETE | Disposable-only composition, explicit service wiring, and safe startup refusal tests pass; root `main.py` remains untouched. |
| R10A | TODO | Run automated parity audit; do not perform manual acceptance. |

## Standing evidence

- Baseline commit: `9a92bb9f679591fbbddb2fd7b1239a4e829d3658`
- Baseline branch: `main`
- Working branch: `refactor/revamped-parallel`
- `python -B scripts/verify.py`: PASS
- `python -B -m unittest discover -s tests -p "test_m*.py"`: PASS, 170 tests
- Protected source data intentionally touched: NO
- Stable `main.py`: LEGACY, unchanged
- Packaging: LOCKED
- Manual GUI, real Chromium, and real Discord checks: NOT PERFORMED
