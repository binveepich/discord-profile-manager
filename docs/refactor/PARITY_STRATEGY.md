# Legacy / Revamped Parity Strategy

Legacy is the oracle; revamped is exercised through explicit disposable
dependencies. New tests never modify the frozen M1–M8 tests.

## Comparison rules

- Pure values and ordered launch arguments require exact equality.
- Errors are compared by category and safety invariant; wording is compared only
  where user-facing compatibility requires it.
- Timestamps use an injected/fixed clock or are normalized before comparison.
- Storage comparison covers normalized catalog/mirror structure, never raw
  Chromium profile contents.
- Stateful scenarios compare invariants after each operation: create/rename/open,
  copy-only migration, metadata recovery, staged deletion, and extension refresh.

## Adapters

`tests/compatibility/legacy_adapter.py` may load the frozen source in an isolated
module for synthetic fixtures. `revamped_adapter.py` constructs `ProjectPaths`,
stores, inspectors, process factories, and services explicitly. Adapters expose
only common vocabulary, not the whole legacy private API.

## Safety

Comparison scripts run only synthetic disposable cases, never launch Chromium,
never print credentials or raw config/profile/log contents, and report
`NOT IMPLEMENTED` until a category has a real comparison. A parity mismatch blocks
the corresponding milestone and never changes `main.py`.
