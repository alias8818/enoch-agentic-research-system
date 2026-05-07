from scripts import validate_public_release


def test_github_metadata_check_rejects_stale_corpus_description(monkeypatch) -> None:
    def fake_fetch(repo: str) -> dict:
        if repo == "alias8818/enoch-ai-research-corpus":
            return {
                "description": "160 AI-generated research artifacts produced by Enoch with provenance metadata.",
                "homepage": "https://alias8818.github.io/enoch-agentic-research-system/",
            }
        return {"description": "Public Enoch release surface.", "homepage": ""}

    monkeypatch.setattr(validate_public_release, "fetch_github_repo_metadata", fake_fetch)
    failures: list[str] = []

    validate_public_release.check_github_metadata(495, failures)

    assert any("artifact count drift in GitHub metadata" in failure for failure in failures)
    assert any("corpus GitHub description does not start" in failure for failure in failures)


def test_github_metadata_check_accepts_current_corpus_description(monkeypatch) -> None:
    def fake_fetch(repo: str) -> dict:
        if repo == "alias8818/enoch-ai-research-corpus":
            return {
                "description": "495 AI-generated research artifacts produced by Enoch with provenance metadata.",
                "homepage": "https://alias8818.github.io/enoch-agentic-research-system/",
            }
        return {"description": "Public Enoch release surface.", "homepage": ""}

    monkeypatch.setattr(validate_public_release, "fetch_github_repo_metadata", fake_fetch)
    failures: list[str] = []

    validate_public_release.check_github_metadata(495, failures)

    assert failures == []


def test_github_metadata_fetch_falls_back_to_authenticated_gh_on_rate_limit(monkeypatch) -> None:
    from urllib.error import HTTPError
    import subprocess

    def fake_urlopen(*args, **kwargs):
        raise HTTPError(
            url="https://api.github.com/repos/alias8818/enoch-ai-research-corpus",
            code=403,
            msg="rate limit exceeded",
            hdrs=None,
            fp=None,
        )

    def fake_run(cmd, text, stdout, stderr, check):
        assert cmd == ["gh", "api", "repos/alias8818/enoch-ai-research-corpus"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"description":"497 AI-generated research artifacts produced by Enoch","homepage":"https://alias8818.github.io/enoch-agentic-research-system/"}',
            stderr="",
        )

    monkeypatch.setattr(validate_public_release, "urlopen", fake_urlopen)
    monkeypatch.setattr(validate_public_release.subprocess, "run", fake_run)

    metadata = validate_public_release.fetch_github_repo_metadata("alias8818/enoch-ai-research-corpus")

    assert metadata["description"].startswith("497 AI-generated research artifacts")
