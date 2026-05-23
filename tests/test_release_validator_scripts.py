from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import generate_ecosystem_manifest, validate_live_public_release


def test_reject_stale_matches_phrase_case_insensitively() -> None:
    failures: list[str] = []

    validate_live_public_release.reject_stale(
        "launch", "This page says 120 AI-generated artifacts.", failures
    )

    assert failures == ["launch contains stale/unscoped phrase: 120 AI-generated"]


def test_live_public_validation_defaults_expected_count_from_manifest(
    monkeypatch,
) -> None:
    manifest = {
        "artifact_count": 388,
        "packaging_provenance_pass_count": 388,
        "gate_name": "packaging_provenance_gate",
        "strict_claim_evidence_pass_count": 3,
        "strict_claim_evidence_total_count": 388,
        "strict_claim_evidence_gate_name": "strict_claim_evidence_audit",
        "strict_claim_evidence_gate_status": "blocked_audit_gaps",
        "not_validated": ["scientific_correctness"],
    }
    launch = (
        "Run local AI research workflows. Run the local proof. packaging/provenance strict claim/evidence "
        '3/388 not peer-reviewed name="enoch-corpus-count" content="388" name="enoch-build-sha" content="abc"'
    )
    profile = "388 artifacts 388/388 packaging/provenance 3/388 strict claim/evidence"
    docs = "Current docs without stale wording"
    hf_summary = {
        "artifact_count": 388,
        "strict_claim_evidence_pass_count": 3,
        "strict_claim_evidence_total_count": 388,
    }
    hf_readme = "This dataset contains 388 AI-generated research artifacts. Current strict claim/evidence audit status is **3 / 388 passing**."
    responses = {
        "https://launch": launch,
        "https://profile": profile,
        "https://manifest": json.dumps(manifest),
        "https://docs": docs,
        "https://hf-summary": json.dumps(hf_summary),
        "https://hf-readme": hf_readme,
    }

    def fake_fetch(url: str) -> tuple[str, str]:
        return responses[url], "text/plain"

    monkeypatch.setattr(validate_live_public_release, "fetch", fake_fetch)

    assert (
        validate_live_public_release.main(
            [
                "--launch",
                "https://launch",
                "--profile",
                "https://profile",
                "--manifest",
                "https://manifest",
                "--docs",
                "https://docs",
                "--hf-summary",
                "https://hf-summary",
                "--hf-readme",
                "https://hf-readme",
            ]
        )
        == 0
    )


def _write_manifest_inputs(corpus: Path) -> None:
    (corpus / "papers").mkdir(parents=True)
    (corpus / "quality").mkdir()
    (corpus / "papers" / "index.json").write_text(
        json.dumps({"count": 1, "papers": [{}]}), encoding="utf-8"
    )
    (corpus / "quality" / "quality_report.json").write_text(
        json.dumps({"count": 1, "passed": 1}), encoding="utf-8"
    )


def test_generate_ecosystem_manifest_rejects_missing_system_and_docs_repos(
    tmp_path, monkeypatch
) -> None:
    corpus = tmp_path / "corpus"
    _write_manifest_inputs(corpus)
    output = tmp_path / "ecosystem.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_ecosystem_manifest.py",
            "--system",
            str(tmp_path / "missing-system"),
            "--docs",
            str(tmp_path / "missing-docs"),
            "--corpus",
            str(corpus),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit, match="system repo path does not exist"):
        generate_ecosystem_manifest.main()
    assert not output.exists()


def test_generate_ecosystem_manifest_includes_promising_signal_count(
    tmp_path, monkeypatch
) -> None:
    system = tmp_path / "system"
    docs = tmp_path / "docs"
    corpus = tmp_path / "corpus"
    promising = tmp_path / "promising"
    system.mkdir()
    docs.mkdir()
    _write_manifest_inputs(corpus)
    (promising / "data").mkdir(parents=True)
    (promising / "data" / "signals.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    output = tmp_path / "ecosystem.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_ecosystem_manifest.py",
            "--system",
            str(system),
            "--docs",
            str(docs),
            "--corpus",
            str(corpus),
            "--promising",
            str(promising),
            "--output",
            str(output),
        ],
    )

    assert generate_ecosystem_manifest.main() == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["promising_signal_count"] == 2
    assert (
        manifest["repos"]["promising_signals"]["name"]
        == "alias8818/enoch-promising-signals"
    )


def test_generate_ecosystem_manifest_rejects_boolean_counts(
    tmp_path, monkeypatch
) -> None:
    system = tmp_path / "system"
    docs = tmp_path / "docs"
    corpus = tmp_path / "corpus"
    system.mkdir()
    docs.mkdir()
    (corpus / "papers").mkdir(parents=True)
    (corpus / "quality").mkdir()
    (corpus / "papers" / "index.json").write_text(
        json.dumps({"count": True, "papers": [{}]}), encoding="utf-8"
    )
    (corpus / "quality" / "quality_report.json").write_text(
        json.dumps({"count": True, "passed": True}), encoding="utf-8"
    )
    output = tmp_path / "ecosystem.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_ecosystem_manifest.py",
            "--system",
            str(system),
            "--docs",
            str(docs),
            "--corpus",
            str(corpus),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(
        SystemExit, match="corpus index count must be a non-negative integer"
    ):
        generate_ecosystem_manifest.main()
    assert not output.exists()
