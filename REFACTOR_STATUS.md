# Refactor Status

## Current status

R0 through R10A and R9B are complete on the isolated branch `refactor/revamped-parallel`.
R13 remains a working-tree milestone without a commit boundary. R14 is
PARTIAL: the product/development boundary, extension policy (only Autofill is
required; the token extractor is optional), account rollback, and integrity
governance are implemented and automated; manual Windows/Tk/Chromium acceptance
is still pending.

AUTOMATED PARITY: PASS
DEFAULT ENTRYPOINT: REACT PRODUCT (`python main.py`); legacy via `python main.py --legacy`
REVAMPED: READY FOR R14 MANUAL ACCEPTANCE
DEFAULT SWITCH: APPROVED BY OWNER (beta prep step 8)
PACKAGING: LOCKED

The stable entrypoint is `main.py`, which starts the React product;
`python main.py --legacy` starts the legacy app. Packaging remains locked.

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
| R14 | PARTIAL | Explicit workspace boundary, transactional account rollback, and immutable-baseline governance implemented. The R14 prohibition on the token extractor was lifted in beta prep: it is now an optional extension, and only Autofill is required. Full automated gates pass; manual acceptance remains required. |

## Standing evidence

- Baseline commit: `ca9c5661fb9cedc2ecaf884c58547a8672bfcf71` (R0 freeze)
- Baseline branch: `main`
- Working branch: `refactor/revamped-parallel`
- `python -B scripts/verify.py`: PASS
- `python -B -m unittest discover -s tests -p "test_*.py"`: PASS, 422 tests, 1 skipped (measured 2026-10-26)
- `python -B -m unittest discover -s tests -p "test_m*.py"`: PASS, 182 tests
- `python -B -m unittest discover -s tests -p "test_r*.py"`: PASS, 135 tests, 1 skipped
- `python -B -m unittest discover -s tests -p "test_*parity.py"`: PASS, 4 tests
- `npm test` in `frontend/` (node --test): PASS, 64 tests; `npx vite build` in `frontend/`: PASS
- `python -B scripts/verify_revamped.py`: PASS, including protected runtime/source and prohibited-extension safety
- `python -B scripts/check_refactor_integrity.py`: PASS, immutable R0 plus named approved milestones
- `python -B scripts/compare_legacy_revamped.py`: PASS
- Protected source data intentionally touched: legacy compatibility source and its milestone test changed only through explicit R14 security remediation, and through the owner-approved beta step 2.5 legacy repair (named milestone `Beta step 2.5 legacy proxy endpoint repair` in `scripts/check_refactor_integrity.py`: `legacy/profile_manager.py`, `tests/test_m5_extensions.py`, `tests/test_m8_proxy.py`); root `main.py` changed only by the owner-approved beta step 8 routing (named milestone `Beta step 8 product entrypoint` in `scripts/check_refactor_integrity.py`)
- Stable `main.py`: starts the React product (beta step 8, owner-approved); `--legacy` starts the legacy app
- Packaging: LOCKED
- R9B GUI launch: available with the explicit disposable `--workspace-root` command; default browser launch is disabled
- R14 development launch: `--workspace-root` below repository `tmp/`; Product launch requires explicit `--product-root` and uses a product-owned marker
- Token-extractor source (`extensions/discord-token-extractor-extension`): kept in the repository as an optional extension; only Autofill is required. Fresh profiles do not receive it unless the global extension policy enables it. An existing copy is not deleted and keeps loading unless that policy disables it. Release builds exclude it (`scripts/release_manifest.json`: `denylist` and `source_only_optional`).
- Manual GUI, real Chromium, and real Discord checks: NOT PERFORMED
