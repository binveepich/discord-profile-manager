# Immutable Refactor Baseline

Captured on 2026-09-15 before any revamped implementation changes.

## Git baseline

- Baseline commit: `9a92bb9f679591fbbddb2fd7b1239a4e829d3658`
- Baseline subject: `M11: add source app manual acceptance checklist`
- Baseline branch: `main`
- Refactor branch: `refactor/revamped-parallel`
- Tracked source diff before refactor: clean
- Pre-existing untracked files: preserved and not staged by R0

## Verification baseline

`python -B scripts/verify.py`: PASS

```text
SYNTAX: PASS
UNIT TESTS: PASS
ENTRYPOINT: PASS
RUNTIME STRUCTURE: PASS
AUTONOMOUS GATE: PASS
```

`python -B -m unittest discover -s tests -p "test_m*.py"`: PASS, 170 tests, OK.

The suite uses disposable fixtures and mocked process/GUI seams. No real
Chromium launch or production account data is part of this baseline run.

## Frozen source hashes

Hashes are Git-compatible blob hashes from the source files as present at the
baseline. They are integrity evidence only; no protected runtime data was read.

| Protected file | Blob hash |
| --- | --- |
| `legacy/profile_manager.py` | `7c4d20b868e47e2be8a9293df78a4d13a63bbeae` |
| `main.py` | `1dd57b45b1c4bfbb574818816e1f3251001d56e0` |
| `tests/test_m1_runtime.py` | `c9321395af0d36775f00dd612617cc43cca18d5c` |
| `tests/test_m2_lifecycle.py` | `aa5a3b8635651bca3fb01ca7b6dc364443dc5941` |
| `tests/test_m3_migration.py` | `60a8831eac1bbef47f780c4c1e1ce4ac0cae697b` |
| `tests/test_m4_metadata.py` | `738a92e04689760b2383ec2f7856d680170d2ec9` |
| `tests/test_m5_extensions.py` | `944be25e6c3f3c9d771a4644f30e3e6ffe85a2b9` |
| `tests/test_m6_gui.py` | `1ba6f5f1e9c5fec23044222325bb6d88368503c4` |
| `tests/test_m7_environment.py` | `f44b0fa59adb00501d6633a3c9939b3858d7c76d` |
| `tests/test_m8_proxy.py` | `68b98fa6112c130f4efb747c045f2a1b8e3ac151` |

## Protected locations

The following remain read-only throughout the refactor: `profiles/`,
`browser/`, `config/profiles.json`, `legacy/data/`, `legacy/log/`, `logs/`, and
existing profile-local extension deployments. New tests use disposable roots
under `tmp/` only.

## Locked decisions and gaps

- `main.py` must continue to delegate to `legacy.profile_manager.main`.
- No package, installer, executable, updater, or Chromium runtime replacement is
  allowed.
- Manual GUI, real Chromium, and real Discord acceptance are still pending.
- The existing legacy account workflow remains plaintext for compatibility; a
  secure migration requires a separate human-reviewed milestone.
- Timezone remains stored-only and proxy support remains unauthenticated/offline.
