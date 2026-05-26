from scripts import validate_public_release


def test_github_metadata_check_rejects_stale_corpus_description(monkeypatch) -> None:
    def fake_fetch(repo: str) -> dict:
        if repo == "alias8818/enoch-ai-research-corpus":
            return {
                "description": "160 AI-generated research artifacts produced by Enoch with provenance metadata.",
                "homepage": "https://alias8818.github.io/enoch-agentic-research-system/",
            }
        return {"description": "Public Enoch release surface.", "homepage": ""}

    monkeypatch.setattr(
        validate_public_release, "fetch_github_repo_metadata", fake_fetch
    )
    failures: list[str] = []

    validate_public_release.check_github_metadata(495, failures)

    assert any(
        "artifact count drift in GitHub metadata" in failure for failure in failures
    )
    assert any(
        "corpus GitHub description does not start" in failure for failure in failures
    )


def test_github_metadata_check_accepts_current_corpus_description(monkeypatch) -> None:
    def fake_fetch(repo: str) -> dict:
        if repo == "alias8818/enoch-ai-research-corpus":
            return {
                "description": "495 AI-generated research artifacts produced by Enoch with provenance metadata.",
                "homepage": "https://alias8818.github.io/enoch-agentic-research-system/",
            }
        return {"description": "Public Enoch release surface.", "homepage": ""}

    monkeypatch.setattr(
        validate_public_release, "fetch_github_repo_metadata", fake_fetch
    )
    failures: list[str] = []

    validate_public_release.check_github_metadata(495, failures)

    assert failures == []


def test_github_metadata_fetch_falls_back_to_authenticated_gh_on_rate_limit(
    monkeypatch,
) -> None:
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

    metadata = validate_public_release.fetch_github_repo_metadata(
        "alias8818/enoch-ai-research-corpus"
    )

    assert metadata["description"].startswith("497 AI-generated research artifacts")


def test_public_count_checks_reject_personal_site_stale_canonical_count(
    tmp_path,
) -> None:
    page = tmp_path / "index.html"
    page.write_text(
        "<p>497 canonical AI-generated papers</p>"
        "<p>497 of 497 pass packaging and provenance lint.</p>",
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_counts(
        [page], artifact_count=377, pass_count=377, failures=failures
    )

    assert any("artifact count drift" in failure for failure in failures)
    assert any(
        "packaging/provenance pass count drift" in failure for failure in failures
    )


def test_public_count_checks_reject_stale_canonical_artifacts_wording(tmp_path) -> None:
    page = tmp_path / "index.html"
    page.write_text(
        "<p>377 canonical AI-generated artifacts indexed</p>", encoding="utf-8"
    )
    failures: list[str] = []

    validate_public_release.check_counts(
        [page], artifact_count=385, pass_count=385, failures=failures
    )

    assert failures == [f"artifact count drift in {page}:1: 377 != 385"]


def test_strict_public_count_checks_reject_personal_site_stale_fail_rate(
    tmp_path,
) -> None:
    page = tmp_path / "index.html"
    page.write_text(
        "<p>My audit gate flags 494 of its own 497 outputs.</p>", encoding="utf-8"
    )
    failures: list[str] = []

    validate_public_release.check_strict_public_counts(
        [page], artifact_count=377, strict_pass_count=3, failures=failures
    )

    assert failures == [
        f"strict audit fail count drift in {page}:1: 494 of 497 != 374 of 377"
    ]


def test_strict_public_count_checks_reject_wrapped_fail_rate(tmp_path) -> None:
    page = tmp_path / "index.md"
    page.write_text(
        "Strict claim/evidence audit fails 999 of its own\n"
        "500 canonical outputs.\n"
        "The strict gate flags 7 of the\t500 outputs.\n",
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_strict_public_counts(
        [page], artifact_count=377, strict_pass_count=3, failures=failures
    )

    assert failures == [
        f"strict audit fail count drift in {page}:1: 999 of 500 != 374 of 377",
        f"strict audit fail count drift in {page}:3: 7 of 500 != 374 of 377",
    ]


def test_strict_public_count_checks_reject_stale_strict_pass_fraction(tmp_path) -> None:
    page = tmp_path / "index.html"
    page.write_text("<p>3/377 pass strict claim/evidence audit.</p>", encoding="utf-8")
    failures: list[str] = []

    validate_public_release.check_strict_public_counts(
        [page], artifact_count=385, strict_pass_count=3, failures=failures
    )

    assert failures == [f"strict audit pass count drift in {page}:1: 3/377 != 3/385"]


def test_hf_export_check_rejects_stale_dataset_summary(tmp_path) -> None:
    hf = tmp_path / "hf"
    hf.mkdir()
    (hf / "dataset_summary.json").write_text(
        '{"artifact_count": 496, "strict_claim_evidence_pass_count": 3, "strict_claim_evidence_total_count": 496}',
        encoding="utf-8",
    )
    (hf / "README.md").write_text(
        "This dataset contains 496 AI-generated research artifacts. "
        "Current strict claim/evidence audit status is **3 / 496 passing**.",
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_hf_export(
        hf, artifact_count=385, strict_pass_count=3, failures=failures
    )

    assert any("HF export artifact_count 496 != 385" in failure for failure in failures)
    assert any("HF export strict total 496 != 385" in failure for failure in failures)
    assert any(
        "HF export README missing current count fragment" in failure
        for failure in failures
    )


def test_public_count_checks_reject_stale_svg_split_count(tmp_path) -> None:
    page = tmp_path / "social-card.svg"
    page.write_text(
        '<text class="m">385 indexed</text><text class="t">AI artifacts</text>',
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_counts(
        [page], artifact_count=388, pass_count=388, failures=failures
    )

    assert failures == [f"artifact count drift in {page}:1: 385 != 388"]


def test_public_secret_token_check_rejects_high_confidence_tokens(tmp_path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(
        "SYNTHETIC_API_KEY=syn_abcdefghijklmnopqrstuvwxyz1234567890\n", encoding="utf-8"
    )
    failures: list[str] = []

    validate_public_release.check_public_secret_tokens([paper], failures)

    assert failures == [f"secret-like token in public release surface {paper}:1"]


def test_public_secret_token_check_rejects_hf_and_anthropic_tokens(tmp_path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(
        "HF_TOKEN=hf_abcdefghijklmnopqrstuvwxyz1234567890\n"
        "ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890abcdefghijklmnopqrstuvwxyz1234567890\n",
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_public_secret_tokens([paper], failures)

    assert failures == [
        f"secret-like token in public release surface {paper}:1",
        f"secret-like token in public release surface {paper}:2",
    ]


def test_public_secret_token_check_rejects_generic_bearer_jwt_and_provider_envs(
    tmp_path,
) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n"
        "SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "abcdefghijklmnopqrstuvwxyz1234567890.abcdefghijklmnopqrstuvwxyz1234567890\n"
        "ENOCH_CONTROL_TOKEN=control-plane-token-value-12345\n",
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_public_secret_tokens([paper], failures)

    assert failures == [
        f"secret-like token in public release surface {paper}:1",
        f"secret-like token in public release surface {paper}:2",
        f"secret-like token in public release surface {paper}:3",
    ]


def test_public_secret_token_check_ignores_redacted_tokens_and_slugs(tmp_path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(
        "SYNTHETIC_API_KEY=[REDACTED_TOKEN]\n"
        "papers/dense-mask-distillation-from-moe/paper.md\n",
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_public_secret_tokens([paper], failures)

    assert failures == []


def test_corpus_public_trust_validator_is_not_executed_by_default(
    monkeypatch, tmp_path
) -> None:
    corpus = tmp_path / "corpus"
    validator = corpus / "scripts" / "validate_public_trust_surfaces.py"
    validator.parent.mkdir(parents=True)
    validator.write_text("raise SystemExit('must not execute')\n", encoding="utf-8")

    def fail_run(*_args, **_kwargs):  # noqa: ANN001 - patched subprocess boundary
        raise AssertionError("validator execution must be opt-in")

    monkeypatch.setattr(validate_public_release.subprocess, "run", fail_run)
    failures: list[str] = []

    validate_public_release.check_corpus_public_trust_validator(corpus, failures)

    assert failures == []


def test_promising_signals_repo_validation_rejects_count_drift(tmp_path) -> None:
    promising = tmp_path / "promising"
    (promising / "data").mkdir(parents=True)
    (promising / "data" / "signals.jsonl").write_text(
        '{"project_id":"p1","status":"useful_signal","do_not_overclaim":{"disclaimer":"These are not validated papers.","not_a_paper":true,"not_peer_reviewed":true,"not_publication_validated":true,"not_in_main_corpus":true},"evidence":{"public_evidence_copied":false}}\n',
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_promising_signals_repo(
        promising, expected_count=2, failures=failures
    )

    assert any(
        "promising_signal_count drift: 1 != 2" in failure for failure in failures
    )


def test_promising_signals_public_paths_are_secret_scanned(tmp_path) -> None:
    promising = tmp_path / "promising"
    (promising / "signals").mkdir(parents=True)
    (promising / "signals" / "example.md").write_text(
        "SYNTHETIC_API_KEY=syn_abcdefghijklmnopqrstuvwxyz1234567890\n", encoding="utf-8"
    )

    paths = validate_public_release.promising_signal_public_paths(promising)
    failures: list[str] = []
    validate_public_release.check_public_secret_tokens(paths, failures)

    assert failures == [
        f"secret-like token in public release surface {promising / 'signals' / 'example.md'}:1"
    ]


def test_promising_signal_count_checks_reject_stale_public_copy(tmp_path) -> None:
    page = tmp_path / "README.md"
    page.write_text(
        "A separate repo preserves 3 bounded promising signals outside the paper corpus.",
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_promising_counts(
        [page], promising_signal_count=4, failures=failures
    )

    assert failures == [f"promising signal count drift in {page}:1: 3 != 4"]


def test_promising_signal_count_checks_allow_formatted_whitespace(tmp_path) -> None:
    page = tmp_path / "README.md"
    page.write_text(
        "A separate repo preserves 3 bounded\npromising\tsignals outside the paper corpus.",
        encoding="utf-8",
    )
    failures: list[str] = []

    validate_public_release.check_promising_counts(
        [page], promising_signal_count=4, failures=failures
    )

    assert failures == [f"promising signal count drift in {page}:1: 3 != 4"]
