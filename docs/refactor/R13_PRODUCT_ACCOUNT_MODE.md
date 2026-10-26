# R13 Product Account Mode

Date: 2026-09-17. Scope: add an explicit synthetic/development versus interactive/product account boundary to the revamped application. The stable root entrypoint, `legacy/`, Chromium runtime, and extension source directories are unchanged.

## Current account data flow

The revamped path is:

`TkRevampedApp` → `ProfileGUIController` → `AccountCompatibilityService` → account persistence → profile-local extension configuration (synthetic mode only) → launch-time `ExtensionService` / `ChromiumLauncher`.

In development mode, the GUI enforces the `@example.invalid` suffix. The
direct compatibility service retains the R6-compatible
`email:password[:totp]` input for legacy/disposable compatibility. R14's
revamped composition sets a stricter boundary: it accepts only a synthetic
identifier and stores no credential-shaped fields.

In product mode, the GUI exposes only an account label and email/account identifier. The controller persists the association through `ProfileService.set_account_metadata()` in the application-owned profile catalog. Product mode does not call extension setup as part of account setup. Launch independently deploys the approved built-ins through the safe R14 extension policy.

## Development / Safe Mode

- Canonical mode: `development` (aliases include `synthetic` and `safe`).
- GUI label: Synthetic Development Mode.
- Normal account domains are rejected by the existing GUI guard; only `@example.invalid` identifiers are accepted there.
- The legacy-compatible local autofill config remains supported for disposable tests only.

## Interactive / Product Mode

- Canonical mode: `product` (alias: `interactive`).
- Select with `revamped.main --product-root <path>` (optionally with
  `--product-mode`) or the explicit `compose_product()` API. Product mode is
  refused when paired with a disposable `--workspace-root`.
- GUI label: Interactive Product Mode.
- Safe persisted shape:

```json
"account": {
  "mode": "product",
  "email": "user@example.com",
  "label": "Primary account"
}
```

The email/account identifier and label are non-sensitive metadata. They survive manager restart and are removed independently from the Chromium profile.

## Sensitive data policy

Secure Windows credential storage is not implemented in R13. Product mode therefore does not accept or persist passwords, authentication tokens, TOTP secrets, or similar authentication values. Credential-shaped product input is rejected before persistence, and the product account view contains no sensitive fields.

The application catalog validator also rejects sensitive field names, including `password`, `token`, `totp`, `credential`, `secret`, `cookie`, and `session`. No product account values are written to `extensions.json` or logs. R13 does not silently migrate existing synthetic plaintext local configs. R14 stages the old local config, clears it, publishes the product association, and restores the old bytes if publication fails.

## Extension account integration

- `discord-autofill-extension` reads `ACCOUNT.email`, `ACCOUNT.password`, and `ACCOUNT.totpSecret` from its profile-local `config.js`. Only synthetic development mode populates this existing disposable config.
- `discord-token-extractor-extension` is optional. Fresh profiles do not receive it by default; valid existing copies are preserved and continue to load unless deliberately disabled. It can be enabled deliberately for deployment to other profiles. Its source remains in the repository but is excluded from release builds.
- `discord-autofill-extension` is the only approved required built-in and remains a launch-time requirement independent of whether a profile has an account association.
- Extension source directories are not modified by R13.

## Compatibility and deletion behavior

Existing catalogs without an `account` object still load unchanged. Synthetic development account APIs remain available. Removing an account clears its association/configuration but never deletes Chromium profile data. Deleting a profile removes its catalog record and profile tree together; there is no separate product account catalog to orphan.

## Verification

The R13 test module covers mode selection, safe metadata persistence/restart, credential-shaped input rejection, account-independent built-in launch, masked GUI display, account removal without profile deletion, and safe profile deletion. The existing R10-R12 tests and the legacy `test_m*.py` suite remain green.
