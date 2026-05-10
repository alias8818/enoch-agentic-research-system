from __future__ import annotations

from scripts.update_public_release_counts import update_text


def test_update_text_rewrites_current_public_count_phrases_without_touching_history() -> None:
    stats = {
        "artifact_count": 384,
        "packaging_pass": 384,
        "strict_pass": 3,
        "strict_fail": 381,
        "empty_claim_ledgers": 263,
        "result_file_refs": 1429,
        "result_file_refs_missing": 1387,
        "post_dedupe_imports": 8,
    }
    text = "\n".join(
        [
            "377 canonical AI-generated artifacts indexed",
            "377/377 pass packaging/provenance lint",
            "3/377 pass strict claim/evidence audit",
            "flags 374 of 377 canonical outputs",
            "For 374 of the 377 papers, the answer is no.",
            "The audit reports 256 empty claim ledgers and 1,387 missing public result-file references.",
            "The script tracked 1,429 result-file references across the cleaned corpus.",
            "After cleanup, the denominator fell from 497 to 376 and 118 claim ledgers were rescued; one later finalized corpus import moved the live denominator to 377.",
            "The result is smaller and more honest: 376 unique topics, not 497 directory entries.",
        ]
    )
    updated = update_text(text, stats)
    assert "384 canonical AI-generated artifacts indexed" in updated
    assert "384/384 pass packaging/provenance lint" in updated
    assert "3/384 pass strict claim/evidence audit" in updated
    assert "flags 381 of 384 canonical outputs" in updated
    assert "For 381 of the 384 papers" in updated
    assert "263 empty claim ledgers" in updated
    assert "1,387 missing public result-file references" in updated
    assert "1,429 result-file references" in updated
    assert "8 later finalized corpus imports moved the live denominator to 384" in updated
    assert "376 unique topics, not 497 directory entries" in updated
    assert "1,1,429" not in updated
