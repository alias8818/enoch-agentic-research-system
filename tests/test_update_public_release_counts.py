from __future__ import annotations

from scripts.update_public_release_counts import update_text


def test_update_text_rewrites_current_public_count_phrases_without_touching_history() -> None:
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
            "377 canonical AI-generated artifacts",
            "377/377 pass packaging/provenance lint",
            "3/377 pass strict claim/evidence audit",
            "3 / 377 pass strict claim and evidence audit.",
            "flags 374 of 377 canonical outputs",
            "My own strict audit gate fails 374 of them.",
            "The strict gate still passes three papers. It rejects the other 374.",
            "For 374 of the 377 papers, the answer is no.",
            "The audit reports 256 empty claim ledgers and 1,387 missing public result-file references.",
            "The script tracked 1,429 result-file references across the cleaned corpus.",
            "After cleanup, the denominator fell from 497 to 376 and 118 claim ledgers were rescued; one later finalized corpus import moved the live denominator to 377.",
            "The result is smaller and more honest: 376 unique topics, not 497 directory entries.",
        ]
    )
    updated = update_text(text, stats)
    assert "385 canonical AI-generated artifacts indexed" in updated
    assert "385 canonical AI-generated artifacts" in updated
    assert "385/385 pass packaging/provenance lint" in updated
    assert "3/385 pass strict claim/evidence audit" in updated
    assert "3/385 pass strict claim and evidence audit." in updated
    assert "flags 382 of 385 canonical outputs" in updated
    assert "strict audit gate fails 382 of them" in updated
    assert "rejects the other 382" in updated
    assert "For 382 of the 385 papers" in updated
    assert "264 empty claim ledgers" in updated
    assert "1,387 missing public result-file references" in updated
    assert "1,429 result-file references" in updated
    assert "9 later finalized corpus imports moved the live denominator to 385" in updated
    assert "376 unique topics, not 497 directory entries" in updated
    assert "1,1,429" not in updated
