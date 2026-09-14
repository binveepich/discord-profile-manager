"""Initial safe comparison harness for the parallel refactor.

R1 intentionally has no implemented behavioral categories yet. The command
reports that truthfully and exits successfully so it can be used as an
infrastructure smoke check. Later milestones replace categories with synthetic
comparisons; no category may be reported PASS without a real comparison.
"""


CATEGORIES = (
    "VALIDATION",
    "PATH POLICY",
    "ENVIRONMENT",
    "PROXY",
    "METADATA",
    "STORAGE",
    "LAUNCH ARGUMENTS",
    "PROFILE LIFECYCLE",
    "GUI MODEL",
)


def main():
    for category in CATEGORIES:
        print(f"{category}: NOT IMPLEMENTED")
    print("LEGACY/REVAMPED PARITY: NOT IMPLEMENTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

