# Refactor Completion Gates

The revamped implementation is not eligible to replace the stable entrypoint
until all of these are demonstrated:

1. Frozen legacy suite remains 170/170 with no changed assertions or source.
2. Revamped unit tests and compatibility tests pass.
3. `scripts/verify.py` still passes and `scripts/verify_revamped.py` passes.
4. The comparison tool reports PASS only for implemented categories and has no
   secret or raw-data output.
5. Freeze-integrity checks identify the immutable R0 baseline, distinguish
   approved milestone blobs, and pass for the legacy module, `main.py`, and
   M1–M8 tests without redefining the baseline.
6. Automated tests use disposable roots and do not write live data or launch the
   production Chromium runtime.
7. Manual GUI/browser/profile acceptance is performed by the user and recorded
   separately; it is never inferred from automated tests.
8. The stable entrypoint remains rollback-safe and continues to run legacy.
9. Packaging, runtime updating, secure credential migration, and new product
   features remain locked.
10. The user explicitly approves any future default-entrypoint switch.
11. R14 product/development root separation is explicit, prohibited extensions
    cannot be required or deployed, product account metadata rejects secrets,
    and manual Windows/Tk/Chromium acceptance is recorded.

R10A is an automated audit only. Reaching it means “ready for USER MANUAL
ACCEPTANCE”, not production approval.
