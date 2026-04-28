# Security policy

Enoch is a control-plane project. Treat its configuration and runtime artifacts as sensitive.

Do not commit:

- bearer tokens or API keys;
- Notion, notification, or model-provider credentials;
- production config files;
- local state databases;
- run logs containing sensitive prompts or environment details;
- generated research artifacts before corpus review.

Recommended pre-push checks:

```bash
uv run pytest -q
grep -RInE '(gho_|github_pat_|sk-[A-Za-z0-9_-]{20,}|ntn_[A-Za-z0-9_-]+|Authorization: Bearer [A-Za-z0-9._-]+)' . --exclude-dir=.git --exclude='uv.lock'
docker run --rm -v "$PWD:/repo:ro" zricethezav/gitleaks:latest detect --source=/repo --no-git --redact
docker run --rm -v "$PWD:/repo:ro" trufflesecurity/trufflehog:latest filesystem /repo --json --no-update
```

If a real secret is ever committed, rotate it. Removing it from the latest commit is not enough if it remains in history.

## Reporting vulnerabilities

Please use GitHub private vulnerability reporting when available, or contact the maintainer privately. Do not disclose exploitable vulnerabilities, leaked credentials, private infrastructure addresses, or private run artifacts in public issues.
