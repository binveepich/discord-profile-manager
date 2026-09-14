"""Explicit adapter for the additive implementation."""

from revamped import core, models


def load_revamped():
    """Return the currently available revamped primitive modules."""
    return {"core": core, "models": models}

