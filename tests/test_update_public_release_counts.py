from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts.update_public_release_counts import (
    artifact_stats,
    default_generated_manifest_path,
    update_text,
)


def test_update_text_rewrites_current_public_count_phrases_without_touching_history() -> (
    None
):
    stats = {
        "artifact_count": 385,
        "packaging_pass": 385,
        "strict_pass": 3,
        "strict_fail": 382,
        "empty_claim_ledgers": 264,
        "result_file_refs": 1429,
        "result_file_refs_missing": 1387,
        "post_dedupe_imports": 9,
    }
    text = "\n".join(
        [
            "377 canonical AI-generated artifacts indexed",
            "<strong>377</strong><span>canonical AI-generated artifacts indexed</span>",
            '<text class="m">377 indexed</text><text class="t">AI artifacts</text>',
            "377 canonical AI-generated artifacts",
            "377 canonical AI-generated research artifacts produced by Enoch",
            "377 canonical indexed artifacts",
            "377/377 pass packaging/provenance lint",
            "<strong>377/377</strong><span>pass packaging/provenance lint</span>",
            "3/377 pass strict claim/evidence audit",
            '<span class="stat">3/377</span><span>pass strict claim/evidence audit</span>',
            "3 / 377 pass strict claim and evidence audit.",
            "Strict audit passes 3/377; the failed claims stay visible.",
            "Current status: **3 / 377 artifacts pass**.",
            "flags 374 of 377 canonical outputs",
            "My own strict audit gate fails 374 of them.",
            "The strict gate still passes three papers. It rejects the other 374.",
            "For 374 of the 377 papers, the answer is no.",
            "The audit reports 256 empty claim ledgers and 1,387 missing public `result_files` references.",
            "The audit reports 256 empty claim ledgers and 1,387 missing public result-file references.",
            "The script tracked 1,429 result-file references across the cleaned corpus.",
            "After cleanup, the denominator fell from 497 to 376 and 118 claim ledgers were rescued; one later finalized corpus import moved the live denominator to 377.",
            "The result is smaller and more honest: 376 unique topics, not 497 directory entries.",
        ]
    )
    updated = update_text(text, stats)
    assert "385 canonical AI-generated artifacts indexed" in updated
    assert (
        "<strong>385</strong><span>canonical AI-generated artifacts indexed</span>"
        in updated
    )
    assert (
        '<text class="m">385 indexed</text><text class="t">AI artifacts</text>'
        in updated
    )
    assert "385 canonical AI-generated artifacts" in updated
    assert "385 canonical AI-generated research artifacts produced by Enoch" in updated
    assert "385 canonical indexed artifacts" in updated
    assert "385/385 pass packaging/provenance lint" in updated
    assert (
        "<strong>385/385</strong><span>pass packaging/provenance lint</span>" in updated
    )
    assert "3/385 pass strict claim/evidence audit" in updated
    assert (
        '<span class="stat">3/385</span><span>pass strict claim/evidence audit</span>'
        in updated
    )
    assert "3/385 pass strict claim and evidence audit." in updated
    assert "Strict audit passes 3/385" in updated
    assert "Current status: **3 / 385 artifacts pass**" in updated
    assert "flags 382 of 385 canonical outputs" in updated
    assert "strict audit gate fails 382 of them" in updated
    assert "rejects the other 382" in updated
    assert "For 382 of the 385 papers" in updated
    assert "264 empty claim ledgers" in updated
    assert "1,387 missing public result-file references" in updated
    assert "1,387 missing public `result_files` references" not in updated
    assert "1,429 result-file references" in updated
    assert (
        "9 later finalized corpus imports moved the live denominator to 385" in updated
    )
    assert "376 unique topics, not 497 directory entries" in updated
    assert "1,1,429" not in updated


def test_update_text_rewrites_wrapped_strict_fail_phrases() -> None:
    stats = {
        "artifact_count": 500,
        "packaging_pass": 500,
        "strict_pass": 492,
        "strict_fail": 8,
        "empty_claim_ledgers": 0,
        "result_file_refs": 0,
        "result_file_refs_missing": 0,
        "post_dedupe_imports": 0,
    }
    text = (
        "Strict claim/evidence audit fails 999 of its own\n"
        "500 canonical outputs.\n"
        "The strict gate flags 7 of the\t500 outputs.\n"
    )

    updated = update_text(text, stats)

    assert "fails 8 of its own\n500 canonical outputs" in updated
    assert "flags 8 of the\t500 outputs" in updated
    assert "999" not in updated
    assert "flags 7" not in updated


def test_update_text_rewrites_promising_signal_count_phrases() -> None:
    stats = {
        "artifact_count": 389,
        "packaging_pass": 389,
        "strict_pass": 389,
        "strict_fail": 0,
        "promising_signal_count": 0,
        "empty_claim_ledgers": 0,
        "result_file_refs": 0,
        "result_file_refs_missing": 0,
        "post_dedupe_imports": 13,
    }
    text = "\n".join(
        [
            "A separate repo preserves 519 bounded promising signals outside the paper corpus.",
            "<strong>519</strong><span>bounded promising</span><span>signals outside the corpus</span>",
            "There are 519 useful/scale-blocked leads preserved for later review.",
        ]
    )

    updated = update_text(text, stats)

    assert "preserves 0 bounded promising signals outside" in updated
    assert (
        "<strong>0</strong><span>bounded promising</span><span>signals outside"
        in updated
    )
    assert "0 useful/scale-blocked leads preserved" in updated
    assert "519" not in updated


def test_update_text_rewrites_strict_fail_denominator_after_large_fail_count() -> None:
    stats = {
        "artifact_count": 1000,
        "packaging_pass": 1000,
        "strict_pass": 500,
        "strict_fail": 500,
        "empty_claim_ledgers": 0,
        "result_file_refs": 0,
        "result_file_refs_missing": 0,
        "post_dedupe_imports": 0,
    }

    updated = update_text("Strict audit flags 494 of its own 500 outputs.", stats)

    assert "flags 500 of its own 1000 outputs" in updated
    assert "flags 1000 of its own 500 outputs" not in updated


def test_default_generated_manifest_path_uses_private_temp_file() -> None:
    path = default_generated_manifest_path()
    try:
        assert path.name.startswith("enoch-ecosystem.generated.")
        assert path.suffix == ".json"
        assert path.parent == Path(tempfile.gettempdir())
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        path.unlink(missing_ok=True)


def test_artifact_stats_rejects_boolean_counts(tmp_path) -> None:
    corpus = tmp_path / "enoch-ai-research-corpus"
    (corpus / "papers").mkdir(parents=True)
    (corpus / "quality").mkdir()
    (corpus / "papers" / "index.json").write_text(
        json.dumps({"count": True, "papers": [{}]}), encoding="utf-8"
    )
    (corpus / "quality" / "quality_report.json").write_text(
        json.dumps({"passed": 1}), encoding="utf-8"
    )
    (corpus / "quality" / "claim_evidence_audit.json").write_text(
        json.dumps({"count": 1, "strict_claim_evidence_pass_count": 1}),
        encoding="utf-8",
    )

    with pytest.raises(
        SystemExit, match="artifact_count must be a non-negative integer"
    ):
        artifact_stats(tmp_path)
