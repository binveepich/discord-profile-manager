"""Explicit adapter for the additive implementation."""

from revamped import core, environment, models, profiles, proxy


def load_revamped():
    """Return the common deterministic/stateful modules used by parity tests."""
    return {
        "core": core,
        "models": models,
        "environment": environment,
        "proxy": proxy,
        "profiles": profiles,
    }
