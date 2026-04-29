# Repository protection plan

These settings are intended before making the repositories public.

## In-repo guardrails

- `CODEOWNERS` assigns default ownership to `@alias8818`.
- PR template requires verification and secret-scan acknowledgement.
- Issue templates steer security reports away from public disclosure.
- Dependabot is enabled for GitHub Actions and Python dependencies where applicable.
- CI workflows run tests/quality checks and gitleaks secret scanning.
- Corpus CI rebuilds the paper index and quality report and fails if generated files drift.

## GitHub settings to apply

For both repositories:

- Issues: enabled.
- Projects/wiki: disabled to reduce moderation surface.
- Discussions: enabled once public if community discussion is desired.
- Delete branch on merge: enabled.
- Vulnerability alerts: enabled where available.
- Private vulnerability reporting: enabled where available.
- Secret scanning / push protection: enabled where available for the account/repo plan.

Branch protection for `main`:

- Require pull request before merge.
- Require at least one approving review.
- Dismiss stale approvals on new commits.
- Require conversation resolution.
- Require status checks before merge.
- Require branches to be up to date before merge.
- Block force pushes and branch deletion.
- Include administrators when the repo is ready to freeze direct pushes.

Required check contexts:

- Code repo: `tests`, `secret-scan`.
- Corpus repo: `quality`, `secret-scan`.

## Automation

Run this after the repositories are public, or after GitHub Pro/organization settings allow branch protection on private repositories:

```bash
scripts/apply-github-protections.sh
```

The non-branch-protection repository settings can be applied while private; branch protection may return HTTP 403 on private repos without the required GitHub plan.

## GitHub Pages

The Pages workflow is manual and preflights whether Pages is enabled. On the current private/free-plan repo, GitHub returns that Pages is not supported. Enable GitHub Pages after public release (or on a plan that supports private Pages), then run `Publish launch site` manually.
