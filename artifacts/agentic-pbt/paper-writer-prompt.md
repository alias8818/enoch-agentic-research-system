# Agentic property-based testing request

You are proposing Hypothesis property tests for a Python code target. Your job is
to infer invariants from source code and existing tests, then emit a compact JSON
proposal. Do not include prose outside JSON.

Target path: enoch_control_plane/control_plane/paper_writer.py

## Requirements

- Propose tests that use `hypothesis` and `pytest`.
- Prefer deterministic, bounded strategies.
- Focus on invariants, round trips, idempotency, path containment, monotonicity,
  schema/field stability, state-transition safety, and error handling.
- Avoid network calls, sleeps, live credentials, destructive filesystem writes,
  or tests that depend on host-specific state.
- Each proposed test must be self-contained Python code.
- Each proposed test must import every target function it uses.
- Respect function signatures from the source excerpt; for example, pass
  `pathlib.Path` values to parameters annotated as `Path`.
- Do not use Hypothesis APIs that may not exist in the installed version.
  Prefer composing `st.text`, `st.lists`, `st.dictionaries`, and
  `pathlib.Path` manually over APIs such as `st.paths`.
- Collection/import/syntax errors are invalid proposals, not counterexamples.
- Valid output shape:

```json
{
  "tests": [
    {
      "name": "short_snake_case_name",
      "rationale": "why this invariant should hold",
      "code": "from hypothesis import given, strategies as st\n..."
    }
  ]
}
```

## Source excerpt

```python
from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path
from typing import Any
from urllib import request

from fastapi import HTTPException

from ..config import GateConfig
from .models import PaperRecord


EVIDENCE_TEXT_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".csv", ".log", ".py"}
EVIDENCE_PUBLIC_DIR = "evidence"
MAX_EVIDENCE_FILES = 80
MAX_PUBLIC_EVIDENCE_BYTES = 80_000
MAX_METRIC_FILES = 40


def _resolve_project_dir(config: GateConfig, candidate: dict[str, Any]) -> Path:
    project_dir_text = str(candidate.get("project_dir") or "").strip()
    if not project_dir_text:
        raise HTTPException(status_code=400, detail="candidate lacks project_dir")
    root = config.expanded_project_root.resolve()
    project_dir = Path(project_dir_text).expanduser()
    if not project_dir.is_absolute():
        project_dir = root / project_dir
    project_dir = project_dir.resolve()
    try:
        project_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="project_dir escapes configured project root") from exc
    return project_dir


def _write_files(project_dir: Path, files: dict[str, str], *, force: bool) -> None:
    for rel_path, content in files.items():
        target = (project_dir / rel_path).resolve()
        try:
            target.relative_to(project_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"paper path escapes project dir: {rel_path}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            continue
        target.write_text(content, encoding="utf-8")


def _blocked_empty_claim_ledger(paper: PaperRecord, *, provider_note: Any) -> str:
    return json.dumps({
        "schema_version": "claim_ledger.v1",
        "paper_id": paper.paper_id,
        "project_id": paper.project_id,
        "run_id": paper.run_id,
        "audit_status": "blocked_empty_claims",
        "claims": [],
        "limitations": [
            "No structured claims were extracted for this artifact.",
            "This artifact must not pass strict claim/evidence audit until claims reference public evidence files.",
        ],
        "writer_provider": provider_note,
    }, indent=2, sort_keys=True) + "\n"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_public_evidence_path(rel_path: Path) -> str:
    safe_parts = [re.sub(r"[^A-Za-z0-9._-]+", "_", part).strip("._") or "artifact" for part in rel_path.parts]
    return str(Path(EVIDENCE_PUBLIC_DIR, *safe_parts))


def _iter_source_evidence_files(project_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    explicit = [
        "run_notes.md",
        ".enoch/project_decision.json",
        ".enoch/metrics.json",
        ".enoch/project.json",
        ".enoch/session.json",
        ".enoch/last_message.md",
        ".omx/project_decision.json",
        ".omx/metrics.json",
    ]
    for rel in explicit:
        path = project_dir / rel
        if path.is_file():
            candidates.append(path)
    for rel_dir in ("results", "logs", "scripts", "prompts", ".enoch/logs", ".enoch/state"):
        root = project_dir / rel_dir
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.suffix.lower() not in EVIDENCE_TEXT_EXTENSIONS:
                continue
            candidates.append(path)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(project_dir)
        except Exception:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique[:MAX_EVIDENCE_FILES]


def _flatten_json_metrics(value: Any, *, prefix: str = "", out: dict[str, Any] | None = None, limit: int = 120) -> dict[str, Any]:
    if out is None:
        out = {}
    if len(out) >= limit:
        return out
    if isinstance(value, dict):
        for key, child in value.items():
            if len(out) >= limit:
                break
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_json_metrics(child, prefix=next_prefix, out=out, limit=limit)
    elif isinstance(value, list):
        if value and all(isinstance(item, (int, float, str, bool)) or item is None for item in value[:20]):
            out[prefix or "list"] = value[:20]
        else:
            for idx, child in enumerate(value[:12]):
                if len(out) >= limit:
                    break
                _flatten_json_metrics(child, prefix=f"{prefix}[{idx}]", out=out, limit=limit)
    elif isinstance(value, (int, float, str, bool)) or value is None:
        if prefix:
            out[prefix] = value
    return out


def _metric_summary_for_file(path: Path, rel_path: str, text: str) -> dict[str, Any] | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            data = json.loads(text)
            metrics = _flatten_json_metrics(data)
            return {"source_path": rel_path, "format": "json", "metrics": metrics}
        if suffix == ".jsonl":
            rows = []
            for line in text.splitlines()[:50]:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
            if rows:
                return {"source_path": rel_path, "format": "jsonl", "rows_sampled": len(rows), "metrics": _flatten_json_metrics(rows)}
    except Exception as exc:
        return {"source_path": rel_path, "format": suffix.lstrip("."), "parse_error": f"{type(exc).__name__}: {exc}"}
    return None


def _build_evidence_bundle_data(
    project_dir: Path,
    candidate: dict[str, Any],
    paper: PaperRecord,
    *,
    writer_provider: Any,
) -> dict[str, Any]:
    source_files = _iter_source_evidence_files(project_dir)
    inventory: list[dict[str, Any]] = []
    public_files: list[dict[str, Any]] = []
    metric_summaries: list[dict[str, Any]] = []
    for path in source_files:
        rel_path = str(path.relative_to(project_dir))
        raw = path.read_text(encoding="utf-8", errors="replace")
        public_content = raw[:MAX_PUBLIC_EVIDENCE_BYTES]
        public_path = _safe_public_evidence_path(Path(rel_path))
        entry = {
            "source_path": rel_path,
            "public_path": public_path,
            "bytes": len(raw.encode("utf-8")),
            "sha256": _sha256_text(raw),
            "truncated": len(raw.encode("utf-8")) > len(public_content.encode("utf-8")),
        }
        inventory.append(entry)
        public_files.append({
            "path": public_path,
            "source_path": rel_path,
            "content": public_content,
            "sha256": _sha256_text(public_content),
            "truncated": entry["truncated"],
        })
        if len(metric_summaries) < MAX_METRIC_FILES:
            summary = _metric_summary_for_file(path, rel_path, raw)
            if summary is not None:
                metric_summaries.append(summary)
    result_refs = [item["path"] for item in public_files]
    return {
        "schema_version": "evidence_bundle.v2",
        "source": "enoch_control_plane",
        "paper_id": paper.paper_id,
        "project_id": paper.project_id,
        "run_id": paper.run_id,
        "source_run_id": str(candidate.get("run_id") or paper.run_id or ""),
        "source_project_dir": str(candidate.get("source_project_dir") or candidate.get("project_dir") or ""),
        "sync_metadata": candidate.get("evidence_sync") or {},
        "writer_provider": writer_provider,
        "file_inventory": inventory,
        "result_file_refs": result_refs,
        "result_artifacts": result_refs,
        "metric_summaries": metric_summaries,
        "public_evidence_files": public_files,
        "limitations": [] if public_files else ["No source evidence files were available for public evidence packaging."],
    }


def _sentence_claims(markdown: str) -> list[str]:
    body = re.sub(r"```.*?```", " ", markdown, flags=re.S)
    body = re.sub(r"^#+\s+.*$", " ", body, flags=re.M)
    raw_sentences = re.split(r"(?<=[.!?])\s+", body)
    claims: list[str] = []
    signal_re = re.compile(
        r"\b(result|measur|improv|reduce|increase|decrease|pass|fail|accuracy|latency|throughput|speed|token|baseline|evidence|validated|tested|observed|showed|found|negative|positive|support)\b|[0-9]",
        re.I,
    )
    skip_re = re.compile(r"\b(ai provenance|operator claims no|readers should treat|unreviewed ai-generated|no independent human review)\b", re.I)
    for sentence in raw_sentences:
        clean = " ".join(sentence.strip().split())
        clean = clean.strip("-* >")
        if len(clean) < 35 or len(clean) > 360:
            continue
        if skip_re.search(clean):
            continue
        if signal_re.search(clean):
            claims.append(clean)
        if len(claims) >= 16:
            break
    return claims


def _tokenize(value: str) -> set[str]:
    return {tok.lower() for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", value)}


def _claim_evidence_matches(claim: str, public_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claim_tokens = _tokenize(claim)
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in public_files:
        text = str(item.get("content") or "")
        haystack = f"{item.get('source_path')} {text[:20000]}"
        evidence_tokens = _tokenize(haystack)
        if not evidence_tokens:
            continue
        overlap = claim_tokens & evidence_tokens
        score = len(overlap) / max(1, len(claim_tokens))
        if score <= 0:
            continue
        quote = ""
        for line in text.splitlines():
            if len(line.strip()) < 20:
                continue
            if _tokenize(line) & claim_tokens:
                quote = line.strip()[:500]
                break
        scored.append((score, {
            "path": str(item.get("path") or ""),
            "source_path": str(item.get("source_path") or ""),
            "sha256": str(item.get("sha256") or ""),
            "match_score": round(score, 4),
            "quote": quote,
        }))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored:
        return [entry for _, entry in scored[:3]]
    fallback: list[dict[str, Any]] = []
    for item in public_files[:2]:
        fallback.append({
            "path": str(item.get("path") or ""),
            "source_path": str(item.get("source_path") or ""),
            "sha256": str(item.get("sha256") or ""),
            "match_score": 0.0,
            "quote": str(item.get("content") or "").splitlines()[0][:500] if str(item.get("content") or "").splitlines() else "",
            "support_level": "weak_context",
        })
    return fallback


def _build_claim_ledger_data(markdown: str, evidence_bundle: dict[str, Any], paper: PaperRecord, *, writer_provider: Any) -> dict[str, Any]:
    claims = []
    public_files = [item for item in evidence_bundle.get("public_evidence_files") or [] if isinstance(item, dict)]
    for idx, claim in enumerate(_sentence_claims(markdown), start=1):
        refs = _claim_evidence_matches(claim, public_files)
        strong = any(float(ref.get("match_score") or 0) > 0 for ref in refs)
        claims.append({
            "id": f"C{idx}",
            "claim": claim,
            "support_status": "supported" if strong else ("weakly_supported" if refs else "unsupported"),
            "evidence_refs": refs,
            "notes": "Matched by l
```

## Existing related tests

```python
# tests/test_control_plane_operator_status.py
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.read_models import OPERATOR_DETAIL_LABELS, OPERATOR_LANE_LABELS, operator_stage_for_record, paper_source_fingerprint
from enoch_control_plane.control_plane.state_contract import OperatorLane
from enoch_control_plane.control_plane.store import REVIEW_CHECKLIST_DEFINITION
from enoch_control_plane.control_plane.router import create_control_plane_router


TOKEN = "test-token"


def _write_decision(project_dir: Path, decision: str) -> None:
    decision_dir = project_dir / ".omx"
    decision_dir.mkdir(parents=True, exist_ok=True)
    (decision_dir / "project_decision.json").write_text(f'{{"decision":"{decision}"}}\n', encoding="utf-8")


def _client(tmp: str) -> TestClient:
    app = FastAPI()
    root = Path(tmp) / "projects"
    root.mkdir(parents=True, exist_ok=True)
    config = GateConfig(
        state_dir=str(Path(tmp) / "state"),
        project_root=str(root),
        dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
        control_api_bearer_token=TOKEN,
        completion_callback_url="http://example.invalid/callback",
        completion_callback_token="unused",
    )

    def require(auth: str | None) -> None:
        if auth != f"Bearer {TOKEN}":
            raise AssertionError("bad token")

    app.include_router(create_control_plane_router(config, require))
    return TestClient(app)


class OperatorStatusTests(unittest.TestCase):
    def test_operator_stage_translates_core_lifecycle_rows(self) -> None:
        cases = [
            ({"status": "queued"}, "ready_queue", "idea_queued", False),
            ({"status": "awaiting_wake"}, "running", "running", False),
            ({"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project"}, "complete_no_paper", "run_complete_no_paper", False),
            ({"status": "completed", "last_run_state": "session_finished_ready", "next_action_hint": "select_next_project"}, "complete_no_paper", "run_complete_no_paper", False),
            ({"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project", "decision_summary": "finalize_negative", "research_outcome": "useful_signal", "hypothesis_status": "supported", "evidence_strength": "moderate", "claim_scope": "toy baseline", "scale_limits": "local toy evidence only"}, "useful_signal", "useful_signal", False),
            ({"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project", "decision_summary": "finalize_negative", "research_outcome": "promising_if_scaled", "hypothesis_status": "supported", "evidence_strength": "moderate", "compute_scale_blocked": True, "scale_limits": "requires datacenter validation"}, "compute_scale_blocked", "compute_scale_blocked", False),
            ({"status": "completed", "last_run_state": "wake_ready", "next_action_hint": "draft_paper_or_select_next_project", "decision_summary": "finalize_negative", "followup_recommended": True, "followup_type": "deepen", "followup_title": "Adjacent test", "followup_hypothesis": "A bounded adjacent hypothesis.", "followup_required_evidence": ["baseline", "metrics"], "followup_success_threshold": "beat baseline", "followup_stop_condition": "stop on miss"}, "followup_investigation", "followup_candidate", False),
            ({"paper_id": "paper-1", "paper_status": "draft_review"}, "automate_publication", "draft_created", False),
            ({"paper_id": "paper-2", "paper_status": "publication_draft", "review_status": "finalized", "finalization_package_path": "package.json"}, "ready_to_publish", "ready_to_publish", False),
            ({"paper_id": "paper-imported", "paper_status": "publication_draft", "review_status": "finalized", "finalization_package_path": "package.json", "corpus_imported": True}, "published", "published", False),
            ({"paper_id": "paper-approved", "paper_status": "publication_draft", "review_status": "approved_for_finalization"}, "automate_publication", "finalization_needed", False),
            ({"paper_id": "paper-finalized-no-package", "paper_status": "publication_draft", "review_status": "finalized"}, "automate_publication", "finalization_needed", False),
            ({"paper_id": "paper-missing-review", "paper_status": "publication_draft"}, "automate_publication", "finalization_needed", False),
            ({"paper_id": "paper-3", "paper_status": "publication_draft", "review_status": "unreviewed"}, "automate_publication", "finalization_needed", False),
            ({"status": "blocked"}, "needs_operator", "blocked_needs_operator", True),
            ({"status": "paused"}, "paused", "paused_work", False),
            ({"status": "canceled"}, "historical", "historical", False),
        ]
        for row, lane, detail_stage, attention in cases:
            with self.subTest(row=row):
                translated = operator_stage_for_record(row)
                self.assertIn(translated["operator_stage"], {item.value for item in OperatorLane})
                self.assertEqual(translated["operator_stage"], lane)
                self.assertEqual(translated["operator_lane"], lane)
                self.assertEqual(translated["operator_detail_stage"], detail_stage)
                self.assertIs(translated["operator_attention"], attention)

    def test_operator_labels_use_grade_school_vocabulary(self) -> None:
        expected_lane_labels = {
            "running": "Running",
            "ready_queue": "Ready",
            "needs_operator": "Needs Attention",
            "complete_no_paper": "Done / No Paper",
            "useful_signal": "Useful Signal",
            "compute_scale_blocked": "Scale Blocked",
            "followup_investigation": "I

# tests/test_control_plane_router.py
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.router import _project_prompt, create_control_plane_router
from enoch_control_plane.control_plane.store import ControlPlaneStore
from enoch_control_plane.control_plane.models import ImportSnapshotRequest, PaperReviewBackfillRequest, WorkerPreflightCheck, WorkerPreflightResponse
from enoch_control_plane.control_plane.worker_adapter import HttpResult


TOKEN = "test-token"


def _config(tmp: str) -> GateConfig:
    root = Path(tmp) / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return GateConfig(
        state_dir=str(Path(tmp) / "state"),
        project_root=str(root),
        dispatch_script_path=str(Path(tmp) / "dispatch.sh"),
        control_api_bearer_token=TOKEN,
        completion_callback_url="http://example.invalid/callback",
        completion_callback_token="unused",
    )


def _live_config(tmp: str) -> GateConfig:
    base = _config(tmp)
    return base.model_copy(update={"live_dispatch_enabled": True, "worker_wake_gate_bearer_token": "worker-token"})


def _client(tmp: str) -> TestClient:
    app = FastAPI()
    config = _config(tmp)
    def require(auth: str | None) -> None:
        if auth != f"Bearer {TOKEN}":
            raise AssertionError("bad token")
    app.include_router(create_control_plane_router(config, require))
    return TestClient(app)


def _client_with_config(config: GateConfig) -> TestClient:
    app = FastAPI()

    def require(auth: str | None) -> None:
        if auth != f"Bearer {TOKEN}":
            raise AssertionError("bad token")

    app.include_router(create_control_plane_router(config, require))
    return TestClient(app)


class ControlPlaneRouterTests(unittest.TestCase):

    def test_health_supports_supabase_backend_without_sqlite_path(self) -> None:
        class FakeSupabaseStore:
            pass

        config = GateConfig(
            state_dir="/tmp/unused",
            project_root="/tmp/unused-projects",
            dispatch_script_path="/tmp/dispatch.sh",
            control_api_bearer_token=TOKEN,
            completion_callback_url="http://example.invalid/callback",
            completion_callback_token="unused",
            control_plane_store_backend="supabase",
            supabase_database_url="postgresql://example.invalid/postgres",
        )
        with patch("enoch_control_plane.control_plane.router.SupabaseControlPlaneStore", return_value=FakeSupabaseStore()):
            client = _client_with_config(config)
            response = client.get("/control/health", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["store_backend"], "supabase")
        self.assertEqual(body["db_path"], "supabase")


    def test_research_quality_endpoint_reads_configured_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "research-quality.json"
            report.write_text(json.dumps({
                "schema_version": "enoch_research_quality_report_v1",
                "generated_at": "2026-05-11T00:00:00Z",
                "summary": {"candidate_count": 0, "decision_count": 1, "problem_counts": {"weak_or_missing_evidence_strength": 1}},
                "candidate_scores": [],
                "decision_scores": [{
                    "project_id": "p1",
                    "project_name": "Project 1",
                    "run_id": "r1",
                    "decision": "finalize_negative",
                    "hypothesis_status": "mixed",
                    "problems": ["weak_or_missing_evidence_strength"],
                }],
            }), encoding="utf-8")
            with patch.dict(os.environ, {"ENOCH_RESEARCH_QUALITY_REPORT_PATH": str(report)}):
                client = _client(tmp)
                response = client.get("/control/api/v1/research-quality", headers={"Authorization": f"Bearer {TOKEN}"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "control_api_v1_research_quality")
        self.assertEqual(body["status"], "warnings")
        self.assertTrue(body["ok"])
        self.assertEqual(body["decisions_checked"], 1)
        self.assertEqual(body["problem_counts"], {"weak_or_missing_evidence_strength": 1})

    def test_pause_import_dry_run_and_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / "idea-positive"
            project_dir.mkdir(parents=True)
            (project_dir / "run_notes.md").write_text("Positive evidence supports drafting this paper.\n", encoding="utf-8")
            client = _client(tmp)
            headers = {"Authorization": f"Bearer {TOKEN}"}

            state = client.get("/control/state", headers=headers).json()
            self.assertTrue(state["flags"]["queue_paused"])

            import_response = client.post("/control/import/legacy-snapshot", headers=headers, json={
                "idempotency_key": "import-router-1",
                "queue_rows": [{
                    "project_id": "idea-positive",
                    "project_name": "Positive Project",
                    "project_dir": str(project_dir),
                    "status": "completed",
                    "last_run_state": "finalize_positive",
                    "current_run_id": "run-1",
                    "manual_review_required": False,
                }],
                "paper_rows": [],
            })
            self.assertEqual(import_response
```
