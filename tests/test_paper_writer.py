from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.models import PaperRecord
from enoch_control_plane.control_plane.paper_writer import write_paper_artifacts


class PaperWriterTests(unittest.TestCase):
    def _config(self, tmp: str, **updates) -> GateConfig:
        root = Path(tmp) / "projects"
        root.mkdir(parents=True, exist_ok=True)
        data = {
            "state_dir": str(Path(tmp) / "state"),
            "project_root": str(root),
            "dispatch_script_path": str(Path(tmp) / "dispatch.sh"),
            "control_api_bearer_token": "token",
            "completion_callback_url": "http://example.invalid/callback",
            "completion_callback_token": "unused",
        }
        data.update(updates)
        return GateConfig(**data)

    def _paper(self) -> PaperRecord:
        return PaperRecord(
            paper_id="idea:run:arxiv_draft",
            project_id="idea",
            run_id="run",
            draft_markdown_path="papers/run/paper.md",
            draft_latex_path="papers/run/paper.tex",
            evidence_bundle_path="papers/run/evidence.json",
            claim_ledger_path="papers/run/claims.json",
            manifest_path="papers/run/manifest.json",
        )

    def test_deterministic_writer_creates_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text("Measured throughput improved by 1.20x against baseline.\n", encoding="utf-8")
            (project / "results").mkdir()
            (project / "results" / "metrics.json").write_text('{"aggregate":{"speedup_mean":1.2},"baseline":"control"}\n', encoding="utf-8")
            meta = write_paper_artifacts(self._config(tmp), {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"}, self._paper(), force=True)
            self.assertEqual(meta["provider"], "deterministic")
            draft = (project / "papers/run/paper.md").read_text(encoding="utf-8")
            self.assertIn("Status: first draft", draft)
            self.assertIn("Automation Status", draft)
            self.assertNotIn("Review Required", draft)
            self.assertNotIn("Human review", draft)
            self.assertTrue((project / "papers/run/manifest.json").exists())
            evidence = json.loads((project / "papers/run/evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["schema_version"], "evidence_bundle.v2")
            self.assertIn("evidence/results/metrics.json", evidence["result_file_refs"])
            self.assertTrue(evidence["public_evidence_files"])
            ledger = json.loads((project / "papers/run/claims.json").read_text(encoding="utf-8"))
            self.assertTrue(ledger["claims"])
            self.assertTrue(ledger["claims"][0]["evidence_refs"])

    def test_synthetic_writer_uses_openai_compatible_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            cfg = self._config(tmp, paper_writer_provider="synthetic.new", paper_writer_api_key="test-key")

            class FakeResponse:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self): return b'{"id":"cmpl-test","choices":[{"message":{"content":"# Model Draft\\n\\nEvidence-grounded."}}]}'

            evidence_path = project / "papers/run/evidence.json"
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text("{\"real\": true}\n", encoding="utf-8")
            (project / "run_notes.md").write_text("Evidence-grounded model draft completed with measured result files.\n", encoding="utf-8")
            with patch("enoch_control_plane.control_plane.paper_writer.request.urlopen", return_value=FakeResponse()) as urlopen:
                meta = write_paper_artifacts(cfg, {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"}, self._paper(), force=True)
            self.assertIn("evidence_bundle.v2", evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["provider"], "synthetic.new")
            self.assertEqual(meta["model"], "hf:zai-org/GLM-5.1")
            self.assertIn("/chat/completions", urlopen.call_args.args[0].full_url)
            payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
            prompt = payload["messages"][1]["content"]
            self.assertIn("Never write TODO", prompt)
            self.assertIn("Referenced artifacts", prompt)
            self.assertIn("Do not require a human reviewer", prompt)
            self.assertNotIn("Mark missing external references as TODO", prompt)
            self.assertIn("# Model Draft", (project / "papers/run/paper.md").read_text())

    def test_synthetic_writer_serializes_datetime_candidate_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text("Evidence-grounded synthetic writer date serialization check.\n", encoding="utf-8")
            cfg = self._config(tmp, paper_writer_provider="synthetic.new", paper_writer_api_key="test-key", paper_writer_fallback_enabled=False)

            class FakeResponse:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self): return b'{"id":"cmpl-test","choices":[{"message":{"content":"# Model Draft\\n\\nEvidence-grounded."}}]}'

            candidate = {
                "project_id": "idea",
                "project_name": "Idea",
                "project_dir": "idea",
                "paper_review_item": {"updated_at": datetime(2026, 5, 9, tzinfo=timezone.utc)},
            }
            with patch("enoch_control_plane.control_plane.paper_writer.request.urlopen", return_value=FakeResponse()) as urlopen:
                meta = write_paper_artifacts(cfg, candidate, self._paper(), force=True)
            self.assertFalse(meta["fallback_used"])
            payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
            self.assertIn("2026-05-09", payload["messages"][1]["content"])

    def test_synthetic_writer_falls_back_without_key_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text("Fallback writer had local source evidence.\n", encoding="utf-8")
            cfg = self._config(tmp, paper_writer_provider="synthetic.new", paper_writer_api_key="", paper_writer_fallback_enabled=True)
            meta = write_paper_artifacts(cfg, {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"}, self._paper(), force=True)
            self.assertTrue(meta["fallback_used"])
            self.assertTrue((project / "papers/run/paper.md").exists())


if __name__ == "__main__":
    unittest.main()
