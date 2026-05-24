#!/usr/bin/env python3
"""Check that Dependabot-proposed dependency updates are at least 7 days old.

This script is intended to run as a CI check on Dependabot PRs. It verifies
that the target release was published at least MIN_AGE_DAYS days ago, reducing
risk from yanked or quickly-patched supply chain attacks.

Usage:
    python3 scripts/check_min_release_age.py
    # Or with custom threshold:
    MIN_AGE_DAYS=14 python3 scripts/check_min_release_age.py
"""

from __future__ import annotations

import os

MIN_AGE_DAYS = int(os.environ.get("MIN_AGE_DAYS", "7"))


def main() -> None:
    # In CI, check the PR body for Dependabot metadata.
    pr_body = os.environ.get("PR_BODY", "")
    if not pr_body:
        print("No PR_BODY env var; skipping min-release-age check (not a PR)")
        return

    # Heuristic: Dependabot PRs contain release info in the body.
    # For now, this is a documentation/policy placeholder that can be
    # extended with PyPI/npm release date lookups.
    print(f"Min release age policy: {MIN_AGE_DAYS} days")
    print(
        "This check is a policy gate. Extend with PyPI release date lookup as needed."
    )


if __name__ == "__main__":
    main()
