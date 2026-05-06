from scripts.validate_supabase_runtime_cutover import compare


def test_compare_accepts_matching_operator_counts_and_safe_pause() -> None:
    live = {
        "write_needed": 0,
        "raw_completed_no_paper_candidates": 215,
        "not_writable_by_decision_gate": 215,
        "publication_ready": 371,
        "needs_attention": 9,
        "flags": {"queue_paused": True, "maintenance_mode": True},
        "state_counts": {"queue_total": 482},
        "paper_counts": {"all": 496},
    }
    supabase = {
        "write_needed": 0,
        "raw_completed_no_paper_candidates": 215,
        "not_writable_by_decision_gate": 215,
        "publication_ready": 371,
        "needs_attention": 9,
        "table_counts": {"queue_items": 482, "papers": 496},
    }

    result = compare(live, supabase)

    assert result.ok
    assert result.failures == []


def test_compare_rejects_mixed_ledgers_and_unpaused_runtime() -> None:
    live = {
        "write_needed": 0,
        "raw_completed_no_paper_candidates": 215,
        "not_writable_by_decision_gate": 215,
        "publication_ready": 371,
        "needs_attention": 9,
        "flags": {"queue_paused": False, "maintenance_mode": False},
        "state_counts": {"queue_total": 482},
        "paper_counts": {"all": 496},
    }
    supabase = {
        "write_needed": 1,
        "raw_completed_no_paper_candidates": 216,
        "not_writable_by_decision_gate": 215,
        "publication_ready": 374,
        "needs_attention": 9,
        "table_counts": {"queue_items": 481, "papers": 495},
    }

    result = compare(live, supabase)

    assert not result.ok
    assert any("write_needed mismatch" in failure for failure in result.failures)
    assert any("raw_completed_no_paper_candidates mismatch" in failure for failure in result.failures)
    assert any("publication_ready mismatch" in failure for failure in result.failures)
    assert any("queue_paused" in failure for failure in result.failures)
    assert any("queue_items count is lower" in failure for failure in result.failures)
    assert any("papers count does not match" in failure for failure in result.failures)
