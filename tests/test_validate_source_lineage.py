from __future__ import annotations

import json

from scripts import validate_source_lineage as vsl


def _snapshot(*, candidates=None, followups=None, sources=None, lineages=None):
    return vsl.SourceLineageSnapshot(
        candidates=list(candidates or []),
        followups=list(followups or []),
        sources=list(sources or []),
        lineages=list(lineages or []),
    )


def test_candidate_source_url_requires_materialized_source():
    source_url = "https://arxiv.org/abs/2605.06546"
    snapshot = _snapshot(
        candidates=[
            {
                "candidate_id": "cand-1",
                "title": "Token superposition branch",
                "source_ids": [],
                "source_urls": [source_url],
            }
        ]
    )

    problems = vsl.validate_snapshot(snapshot)

    assert {problem["kind"] for problem in problems} == {"candidate_source_url_missing_source"}
    assert problems[0]["expected_source_id"] == vsl.source_id_for_url(source_url)


def test_candidate_source_url_passes_with_source_and_generated_from_lineage():
    source_url = "https://arxiv.org/abs/2605.06546"
    source_id = vsl.source_id_for_url(source_url)
    snapshot = _snapshot(
        candidates=[
            {
                "candidate_id": "cand-1",
                "title": "Token superposition branch",
                "source_ids": [],
                "source_urls": [source_url],
            }
        ],
        sources=[{"source_id": source_id, "source_kind": "arxiv", "url": source_url}],
        lineages=[
            {
                "source_type": "source",
                "source_id": source_id,
                "target_type": "candidate",
                "target_id": "cand-1",
                "relation_type": "generated_from",
            }
        ],
    )

    assert vsl.validate_snapshot(snapshot) == []


def test_followup_requires_parent_run_source_and_project_lineage():
    snapshot = _snapshot(
        followups=[
            {
                "idea_id": "followup-1",
                "title": "Follow-up branch",
                "source_external_url": "enoch://control-plane/projects/parent/runs/run-1",
                "source_payload_json": {"parent_project_id": "parent", "parent_run_id": "run-1"},
            }
        ]
    )

    problems = vsl.validate_snapshot(snapshot)

    assert {problem["kind"] for problem in problems} == {
        "followup_missing_parent_run_source",
        "followup_missing_parent_project_lineage",
    }
    parent_source = next(problem for problem in problems if problem["kind"] == "followup_missing_parent_run_source")
    assert parent_source["expected_source_id"] == vsl.followup_parent_source_id("parent", "run-1")


def test_followup_passes_with_parent_run_source_and_lineage_edges():
    parent_source_id = vsl.followup_parent_source_id("parent", "run-1")
    snapshot = _snapshot(
        followups=[
            {
                "idea_id": "followup-1",
                "title": "Follow-up branch",
                "source_external_url": "enoch://control-plane/projects/parent/runs/run-1",
                "source_payload_json": {"parent_project_id": "parent", "parent_run_id": "run-1"},
            }
        ],
        sources=[
            {
                "source_id": parent_source_id,
                "source_kind": "followup_parent_run",
                "url": "enoch://control-plane/projects/parent/runs/run-1",
            }
        ],
        lineages=[
            {
                "source_type": "source",
                "source_id": parent_source_id,
                "target_type": "candidate",
                "target_id": "followup-1",
                "relation_type": "generated_from",
            },
            {
                "source_type": "project",
                "source_id": "parent",
                "target_type": "project",
                "target_id": "followup-1",
                "relation_type": "followup_parent",
            },
        ],
    )

    assert vsl.validate_snapshot(snapshot) == []


def test_report_summarizes_problem_counts():
    report = vsl.build_report(
        _snapshot(
            candidates=[
                {
                    "candidate_id": "cand-1",
                    "title": "Unsourced",
                    "source_ids": ["src-missing"],
                    "source_urls": [],
                }
            ]
        ),
        created_after="2026-05-19T00:00:00Z",
    )

    assert report["ok"] is False
    assert report["created_after"] == "2026-05-19T00:00:00Z"
    assert report["counts"]["candidates"] == 1
    assert report["problem_counts"] == {"candidate_source_id_missing_source": 1}


def test_fetch_snapshot_uses_read_only_provenance_queries(monkeypatch):
    executed: list[tuple[str, dict[str, str | None]]] = []

    class FakeResult:
        def fetchall(self):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            executed.append((sql, params))
            return FakeResult()

    class FakePsycopg:
        def connect(self, database_url, row_factory=None):
            assert database_url == "postgres://example"
            assert row_factory is not None
            return FakeConnection()

    monkeypatch.setitem(__import__("sys").modules, "psycopg", FakePsycopg())
    monkeypatch.setitem(__import__("sys").modules, "psycopg.rows", type("Rows", (), {"dict_row": object()})())

    snapshot = vsl.fetch_snapshot("postgres://example", created_after="2026-05-19T00:00:00Z")

    assert snapshot == _snapshot()
    assert len(executed) == 4
    assert all("enoch.research_" in sql or "enoch.ideas" in sql for sql, _ in executed)
    assert all("notion" not in sql.lower() and "title like" not in sql.lower() for sql, _ in executed)
    assert [params for _, params in executed] == [
        {"created_after": "2026-05-19T00:00:00Z"},
        {"created_after": "2026-05-19T00:00:00Z"},
        None,
        None,
    ]


def test_report_includes_operational_status_schema_and_output(tmp_path):
    report = vsl.build_report(
        _snapshot(
            candidates=[
                {
                    "candidate_id": "cand-1",
                    "title": "Unsourced",
                    "source_ids": ["src-missing"],
                    "source_urls": [],
                }
            ]
        ),
        created_after="2026-05-19T17:51:00Z",
    )

    assert report["schema_version"] == "enoch_source_lineage_report_v1"
    assert report["status"] == "blocked"
    assert report["ok"] is False

    output = tmp_path / "source-lineage" / "latest-report.json"
    assert vsl.write_report(report, output) == output
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "enoch_source_lineage_report_v1"
    assert loaded["status"] == "blocked"

def test_synthesized_candidate_requires_branch_and_reflection_lineage():
    snapshot = _snapshot(
        candidates=[
            {
                "candidate_id": "oracle-1",
                "title": "Oracle",
                "source_ids": [],
                "source_urls": [],
                "raw_candidate_json": {"synthesized_from": ["branch-1"], "reflection_source_ids": ["positive-1"]},
            }
        ]
    )

    problems = vsl.validate_snapshot(snapshot)

    assert {problem["kind"] for problem in problems} == {
        "synthesized_candidate_missing_branch_lineage",
        "synthesized_candidate_missing_reflection_lineage",
    }


def test_synthesized_candidate_passes_with_branch_and_reflection_lineage():
    snapshot = _snapshot(
        candidates=[
            {
                "candidate_id": "oracle-1",
                "title": "Oracle",
                "source_ids": [],
                "source_urls": [],
                "raw_candidate_json": {"synthesized_from": ["branch-1"], "reflection_source_ids": ["positive-1"]},
            }
        ],
        lineages=[
            {
                "source_type": "candidate",
                "source_id": "branch-1",
                "target_type": "candidate",
                "target_id": "oracle-1",
                "relation_type": "synthesized_from",
            },
            {
                "source_type": "candidate",
                "source_id": "branch-1",
                "target_type": "candidate",
                "target_id": "oracle-1",
                "relation_type": "superseded_by",
            },
            {
                "source_type": "project",
                "source_id": "positive-1",
                "target_type": "candidate",
                "target_id": "oracle-1",
                "relation_type": "inspired_by_success",
            },
        ],
    )

    assert vsl.validate_snapshot(snapshot) == []
