"""Development-only composition root, populated in R9.

This placeholder deliberately performs no startup work when imported or run.
The stable root ``main.py`` remains the legacy entrypoint.
"""


def main(_argv=None):
    """Refuse until the explicit disposable development interface is available."""
    raise SystemExit(
        "revamped.main is not ready yet; no stateful development operation was run."
    )


if __name__ == "__main__":
    main()

