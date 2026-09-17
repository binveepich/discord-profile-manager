# Architecture and Product Decisions

## D1 — Packaging is locked

Decision:

Packaging is not part of the current autonomous scope.

Reason:

The user wants to manually review and approve the source-code application before creating `.exe`, installer, or release artifacts.

Effect:

M12 remains LOCKED until explicit user approval.

## D2 — Keep `legacy/profile_manager.py` as implementation entry for now

Decision:

Do not move or split the monolithic implementation during M9.

Reason:

The file is currently the working app entry. Moving logic during source-stability work increases regression risk.

Effect:

A root-level `main.py` wrapper is acceptable, but broad modularization is separate future work.

## D3 — Full unit suite is mandatory

Decision:

Every completed milestone must pass the full unit suite.

Reason:

The suite is fast enough and covers core profile, metadata, extension, GUI-model, environment, and proxy behavior.

Effect:

No milestone can be marked complete while the full suite fails.

## D4 — Smoke test is diagnostic, not a hard release gate

Decision:

`tests/browser_smoke_m2.py` is useful, but failures must be interpreted carefully.

Reason:

It can fail due to local Chromium/Windows graphics/cache environment issues that do not necessarily prove visible GUI launch is broken.

Effect:

Report smoke results separately from unit tests.

## D5 — Secure credential migration is not an overnight autonomous task yet

Decision:

Do not implement real secure credential migration against live profile data without a dedicated design and human checkpoint.

Reason:

It touches AccountManager, extension config, import workflow, migration, and Windows protected storage. It can risk exposing or losing secrets.

Effect:

Credential security remains a future dedicated milestone.

## D6 — M8 proxy scope is narrow

Decision:

M8 supports optional unauthenticated proxy endpoint metadata and launch switches only.

Reason:

Requirements do not require auth, rotation, health checking, or provider integration.

Effect:

Do not expand M8 into proxy auth/rotation/provider work.
