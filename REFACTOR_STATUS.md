# Refactor Status

## Current status

R0 is complete on the isolated branch `refactor/revamped-parallel`.
R1 is next. The stable entrypoint remains legacy and packaging remains locked.

## Milestones

| Milestone | Status | Evidence / next action |
| --- | --- | --- |
| R0 | COMPLETE | Baseline frozen; `verify.py` PASS; frozen suite 170/170; see `docs/refactor/BASELINE.md`. |
| R1 | TODO | Add side-effect-free scaffolding, disposable adapters, and integrity checks. |
| R2 | TODO | Add safe core/model primitives after R1. |
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
