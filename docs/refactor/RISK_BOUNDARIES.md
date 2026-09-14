# Refactor Risk Boundaries

## Safe autonomous scope

Synthetic tests, pure policy, source-only documentation, explicit dependency
injection, fault-injection fixtures, integrity checks, and development-only code
under `revamped/` are in scope.

## Protected / human-checkpoint scope

Do not touch live profiles, Chromium runtime, application metadata, legacy state,
logs, or existing extension deployments. Do not migrate credential storage,
launch real Chromium, perform manual GUI/Discord acceptance, switch the default
entrypoint, package the application, update the runtime, add proxy auth/rotation,
add token extraction, or add anti-detection/fingerprint spoofing.

## High-risk invariants

- Resolve and mutate only explicit contained paths; reject links/reparse points.
- Never auto-repair malformed metadata or recreate missing profile directories.
- Publish metadata only after successful structure/copy stages.
- Stage destructive deletes and restore on publication failure.
- Leave migration sources untouched on every success/failure path.
- Fail closed when Chromium process identity cannot be inspected.
- Keep secrets out of logs, catalog data, comparison output, and error text.
