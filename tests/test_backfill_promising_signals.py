from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backfill_promising_signals.py"
spec = importlib.util.spec_from_file_location("backfill_promising_signals", SCRIPT)
assert spec and spec.loader
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)


def _row(**overrides):
    row = {
        "project_id": "missing-source",
        "run_id": "missing-source-20260519T000000+0000",
        "project_name": "Missing Source",
        "decision_summary": "finalize_negative (project decision is not positive)",
        "research_outcome": "useful_signal",
        "hypothesis_status": "mixed",
        "evidence_strength": "moderate",
        "claim_scope": "Bounded local/toy evidence only.",
        "scale_limits": "No full-scale model training was performed.",
        "useful_signal_summary": "Synthetic proxy showed a mechanism worth preserving.",
        "stop_reason": "No-paper closure because validation was not publication-grade.",
        "recommended_next_action": "Run a bounded direct follow-up.",
        "followup_recommended": True,
        "followup_type": "deepen",
        "followup_title": "Direct follow-up",
        "followup_hypothesis": "The mechanism transfers to a direct small model test.",
        "followup_required_evidence": ["direct model metrics"],
        "followup_success_threshold": "beats baseline by 10%",
        "followup_stop_condition": "stop if no baseline lift",
        "followup_depth": 1,
        "source_ids": [],
        "source_urls": [],
        "source_titles": [],
        "artifact_root": "/var/lib/enoch-control-plane/projects/missing-source",
        "artifact_paths": ["run_notes.md", ".enoch/project_decision.json"],
        "has_live_paper_row": False,
        "write_needed": False,
        "bounded_paper_ready": False,
        "compute_scale_blocked": False,
        "updated_at": "2026-05-19T00:00:00Z",
    }
    row.update(overrides)
    return row


def test_cli_writes_report_and_backfilled_rows_without_private_paths(tmp_path) -> None:
    input_json = tmp_path / "rows.json"
    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    backfilled_rows = tmp_path / "backfilled.json"
    input_json.write_text(
        json.dumps([_row(updated_at=datetime(2026, 5, 19, tzinfo=timezone.utc).isoformat())]),
        encoding="utf-8",
    )

    rc = backfill.main(
        [
            "--input-json",
            str(input_json),
            "--report-json",
            str(report_json),
            "--report-markdown",
            str(report_md),
            "--backfilled-rows-json",
            str(backfilled_rows),
        ]
    )

    assert rc == 0
    report = json.loads(report_json.read_text(encoding="utf-8"))
    rows = json.loads(backfilled_rows.read_text(encoding="utf-8"))
    assert report["summary"]["backfilled_exportable"] == 1
    assert rows[0]["source_records"][0]["source_id"] == "internal_generated:missing-source"
    serialized = report_json.read_text(encoding="utf-8") + report_md.read_text(encoding="utf-8") + backfilled_rows.read_text(encoding="utf-8")
    assert "/var/lib/enoch-control-plane" not in serialized


def test_sanitized_backfilled_rows_handle_live_datetime_values() -> None:
    rows = backfill._sanitized_backfilled_rows([_row(updated_at=datetime(2026, 5, 19, tzinfo=timezone.utc))])

    assert rows[0]["updated_at"].startswith("2026-05-19")
    json.dumps(rows, sort_keys=True)
