from scripts.audit_research_dedupe_loss import audit, classify, text_similarity


def test_text_similarity_catches_topic_family() -> None:
    assert text_similarity("SSM memory sparse anchors", "sparse anchor SSM memory recall") > 0.25


def test_classify_duplicate_suppress_without_material_delta() -> None:
    candidate = {
        "mechanism": "same mechanism",
        "implementation": "same test",
        "baseline_to_beat": "same baseline",
        "success_threshold": "same threshold",
        "kill_condition": "same kill",
        "required_evidence": ["same evidence"],
    }
    prior = {
        "mechanism": "same mechanism",
        "implementation": "same test",
        "baseline_to_beat": "same baseline",
        "success_threshold": "same threshold",
        "kill_condition": "same kill",
        "prior_required_evidence": ["same evidence"],
    }
    variant_type, could_branch, *_ = classify(candidate, prior, 0.9)
    assert variant_type == "duplicate_suppress"
    assert could_branch is False


def test_audit_ranks_failure_addressing_variant_as_branch_candidate() -> None:
    candidates = [{
        "candidate_id": "c1",
        "status": "needs_review",
        "admission_decision": "needs_review",
        "title": "SSM memory direct scale ablation",
        "category": "long-context",
        "hypothesis": "An SSM memory can recover facts if direct anchors are ablated at medium scale.",
        "mechanism": "Adds direct anchor ablation and medium scale validation.",
        "description": "SSM memory variant",
        "implementation": "Run medium scale direct evidence with ablations and GPT-2 scale baseline.",
        "baseline_to_beat": "Dense GPT-2 style baseline",
        "success_threshold": "Beat baseline by 5 percent",
        "kill_condition": "Stop if scale and ablation do not improve",
        "required_evidence": ["direct medium run", "ablation"],
        "novelty_comparison": "Addresses prior proxy-only negative by adding direct evidence.",
        "risk_notes": "Prior negative was proxy-only.",
        "total_score": 70,
    }]
    priors = [{
        "project_id": "p1",
        "project_name": "SSM memory sparse anchors",
        "category": "long-context",
        "description": "SSM memory sparse anchors",
        "implementation": "Small proxy lookup test only",
        "baseline_to_beat": "Vector retrieval",
        "kill_condition": "Stop if proxy fails",
        "decision_gate_state": "negative",
        "project_decision": "finalize_negative",
        "hypothesis_status": "mixed",
        "stop_reason": "Proxy-only negative result lacks direct evidence.",
        "recommended_next_action": "Need direct medium validation.",
    }]
    report = audit(candidates, priors, threshold=0.05)
    assert report["findings"][0]["variant_type"] == "branch_candidate"
    assert report["findings"][0]["could_have_been_good_branch"] is True
