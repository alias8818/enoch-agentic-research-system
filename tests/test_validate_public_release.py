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
