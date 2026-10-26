# R14 Product Boundary and Safe Runtime Composition

Date: 2026-09-17. Status: PARTIAL — automated boundary and integrity work is
implemented; manual Windows/Tk/Chromium acceptance remains outstanding.

## Objective

Create a strict, explicit, and testable boundary between disposable
development mode and future product mode while restoring extension-security
and source-integrity guarantees. R14 does not switch the root entrypoint.

## Scope

- Centralize explicit workspace-root validation.
- Keep development mode below the repository `tmp/` root.
- Add an explicit product-root composition that never adopts unmarked legacy
  state.
- Store only approved product account metadata: mode, label, and account
  identifier.
- Keep the token-extractor source available as an optional repository
  extension. Do not deploy it to fresh profiles by default; preserve valid
  existing copies, allow deliberate enablement, and exclude the source from
  release builds.
- Verify the immutable R0 source baseline separately from named milestone
  changes and current working-tree changes.
- Make account metadata/configuration transitions recoverable on write failure.

## Non-goals

R14 does not switch `main.py`, package or install the application, migrate live
profiles, modify Chromium, store real credentials, add credential/token
extraction, add fingerprint spoofing, rotate or authenticate proxies, update
the browser runtime, or clean up existing user data automatically.

## Architecture changes

`revamped.core` owns shared workspace containment and product-root approval.
Development composition uses `compose(..., workspace_kind="development")` and
`compose_product(product_root, ...)` is the only product composition helper.
Product roots are explicit and carry a small product-owned marker; an existing
unmarked non-empty root is refused without importing or changing its data.

The extension service separates required built-ins from optional discovered
sources. Autofill is the only required extension. When its source is valid, the
token extractor appears as optional and can be enabled deliberately. It is not
deployed to fresh profiles by default, while valid existing profile copies are
preserved and remain loadable. The source stays in the repository but is
excluded from release builds.

Account transitions stage the previous local configuration, clear it, publish
the new application metadata atomically, and restore the previous bytes if
publication fails. Account removal uses the same recoverable order.

## Safety invariants

- Development state is explicitly below repository `tmp/` and cannot resolve
  to the repository root or live profile/config roots.
- Product state requires `--product-root` or the explicit `compose_product()`
  API. `--account-mode product --workspace-root ...` is refused.
- Product roots cannot be the repository live roots or an unmarked non-empty
  directory. No legacy data is migrated or inferred.
- Product catalog records reject password, token, TOTP, session, cookie,
  credential, secret, and equivalent field names.
- Synthetic development account input remains restricted to
  `@example.invalid` and is disposable compatibility behavior.
- The token extractor is optional and is not auto-deployed to fresh profiles.
  Existing valid copies remain in the launch path unless deliberately disabled.
  Deliberate enablement can deploy it to other profiles; its source is excluded
  from release builds.
- The root `main.py`, browser runtime, live profiles, live config, and logs are
  not changed by automated R14 tests.
- A source-integrity PASS names the immutable R0 baseline and separately labels
  approved milestone blobs; it does not replace the baseline hash after an
  unapproved change.

## Expected files

- `revamped/core.py`: centralized workspace policy and product marker.
- `revamped/main.py`: explicit development/product composition and CLI roots.
- `revamped/extensions.py`: required Autofill, optional-source discovery, and
  preservation of existing token-extractor deployments.
- `revamped/accounts.py`: recoverable account transitions and secret-field
  rejection.
- `revamped/profiles.py`: strict account metadata field validation.
- `revamped/gui.py`: product/development workspace labeling.
- `legacy/profile_manager.py`: legacy compatibility path discovers the source
  as optional and does not deploy it through the required-extension path.
- `scripts/check_refactor_integrity.py`: immutable-baseline and approved-change
  governance.
- `scripts/verify_revamped.py`: protected-runtime and extension-security gates.
- `tests/test_r14_product_boundary.py`: disposable-root R14 coverage.
- `docs/refactor/R14_PRODUCT_BOUNDARY.md`: this specification and status.

## Test plan

Automated tests use only disposable roots under repository `tmp/`. They cover
development/product root separation, refusal of repository and unmarked roots,
safe product metadata, sensitive input rejection, optional-extension
availability, default-off deployment, preservation of existing copies, policy
migration, account rollback, integrity classification, ignored runtime snapshot
mutation detection, root `main.py` integrity, and the existing regression/parity
suites.

## Manual acceptance plan

On Windows, manually verify the visible development GUI, the product-root
marker and restart behavior, missing/malformed product-root refusal, browser
launch opt-in behavior, and extension state in `chrome://extensions`. Confirm a
fresh profile does not receive a token-extractor deployment by default and that
valid existing copies remain available to load. Use synthetic accounts only. Do
not use live profiles or real Discord credentials. Record Tk/Chromium results
separately from automated results.

## Completion criteria

R14 may be marked COMPLETE only when:

1. The boundary and extension policy are documented and enforced.
2. The immutable-baseline verifier, approved-milestone governance, and root
   entrypoint checks pass.
3. All required automated commands pass without live-state mutation.
4. Product account updates are recoverable and contain no secret fields.
5. Manual Windows/Tk/Chromium acceptance evidence is recorded.

Until item 5 is complete, the status remains PARTIAL and packaging/default
entrypoint switching remain locked.
