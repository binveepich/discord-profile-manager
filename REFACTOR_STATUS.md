# Refactor Status

## Current status

R0 through R10A and R9B are complete on the isolated branch `refactor/revamped-parallel`.
R13 remains a working-tree milestone without a commit boundary. R14 is
PARTIAL: the product/development boundary, extension quarantine, account
rollback, and integrity governance are implemented and automated; manual
Windows/Tk/Chromium acceptance is still pending.

AUTOMATED PARITY: PASS
LEGACY DEFAULT: UNCHANGED
REVAMPED: READY FOR R14 MANUAL ACCEPTANCE
DEFAULT SWITCH: BLOCKED PENDING USER APPROVAL
PACKAGING: LOCKED

The stable entrypoint remains legacy and packaging remains locked.

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
| R9B | COMPLETE | Visible `REVAMPED DEV` Tk shell, disposable-only GUI safety, clean shutdown, and all requested automated gates PASS. Browser launch is opt-in only. |
| R10A | COMPLETE | `verify_revamped.py`, frozen integrity, all synthetic compatibility categories, and all automated audit checks PASS. Manual acceptance remains user-owned. |
| R13 | PARTIAL | Product/development account mode exists in the working tree; product metadata and strict composed-development identity tests pass. No clean milestone commit exists yet. |
| R14 | PARTIAL | Explicit workspace boundary, prohibited-extension quarantine, transactional account rollback, and immutable-baseline governance implemented. Full automated gates pass; manual acceptance remains required. |

## Standing evidence

- Baseline commit: `ca9c5661fb9cedc2ecaf884c58547a8672bfcf71` (R0 freeze)
- Baseline branch: `main`
- Working branch: `refactor/revamped-parallel`
- `python -B scripts/verify.py`: PASS
- `python -B -m unittest discover -s tests -v`: PASS, 307 tests, 1 skipped
- `python -B -m unittest discover -s tests -p "test_m*.py"`: PASS, 173 tests
- `python -B -m unittest discover -s tests -p "test_r*.py"`: PASS, 131 tests, 1 skipped
- `python -B -m unittest discover -s tests -p "test_*parity.py"`: PASS
- `python -B scripts/verify_revamped.py`: PASS, including protected runtime/source and prohibited-extension safety
- `python -B scripts/check_refactor_integrity.py`: PASS, immutable R0 plus named approved milestones
- `python -B scripts/compare_legacy_revamped.py`: PASS
- Protected source data intentionally touched: legacy compatibility source and its milestone test changed only through explicit R14 security remediation; root `main.py` unchanged
- Stable `main.py`: LEGACY, unchanged
- Packaging: LOCKED
- R9B GUI launch: available with the explicit disposable `--workspace-root` command; default browser launch is disabled
- R14 development launch: `--workspace-root` below repository `tmp/`; Product launch requires explicit `--product-root` and uses a product-owned marker
- R14 token-extractor source: retained on disk for quarantine/audit only; not required, enabled, staged, or launched
- Manual GUI, real Chromium, and real Discord checks: NOT PERFORMED
