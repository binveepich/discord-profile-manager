# Refactor Status

## Current status

R0, R1, and R2 are complete on the isolated branch `refactor/revamped-parallel`.
R3 is next. The stable entrypoint remains legacy and packaging remains locked.

## Milestones

| Milestone | Status | Evidence / next action |
| --- | --- | --- |
| R0 | COMPLETE | Baseline frozen; `verify.py` PASS; frozen suite 170/170; see `docs/refactor/BASELINE.md`. |
| R1 | COMPLETE | Commit `R1: add parallel refactor contract infrastructure`; 5 R1 tests, frozen suite 170/170, and integrity check PASS. |
| R2 | COMPLETE | Core/path/model primitives and deterministic parity committed; 186-test full suite and integrity gate PASS. One symlink test is skipped because the host disallows symlink creation. |
| R3 | TODO | Add environment/proxy policy after R2. |
| R4 | TODO | Add disposable storage boundaries after R3. |
| R5 | TODO | Add injected process/launcher services after R4. |
| R6 | TODO | Add extension/account compatibility after R5. |
| R7 | TODO | Add profile lifecycle after R6. |
| R8 | TODO | Add GUI model/controller after R7. |
| R9 | TODO | Add safe development composition after R8. |
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
