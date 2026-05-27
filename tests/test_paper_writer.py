from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from enoch_control_plane.config import GateConfig
from enoch_control_plane.control_plane.models import PaperRecord
from fastapi import HTTPException

from enoch_control_plane.control_plane.paper_writer import (
    _build_claim_ledger_data,
    _sentence_claims,
    _write_files,
    backfill_paper_evidence_artifacts,
    write_paper_artifacts,
)


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
            (project / "run_notes.md").write_text(
                "Measured throughput improved by 1.20x against baseline.\n",
                encoding="utf-8",
            )
            (project / "results").mkdir()
            (project / "results" / "metrics.json").write_text(
                '{"aggregate":{"speedup_mean":1.2},"baseline":"control"}\n',
                encoding="utf-8",
            )
            meta = write_paper_artifacts(
                self._config(tmp),
                {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"},
                self._paper(),
                force=True,
            )
            self.assertEqual(meta["provider"], "deterministic")
            draft = (project / "papers/run/paper.md").read_text(encoding="utf-8")
            self.assertIn("Status: first draft", draft)
            self.assertIn("Automation Status", draft)
            self.assertNotIn("Review Required", draft)
            self.assertNotIn("Human review", draft)
            self.assertTrue((project / "papers/run/manifest.json").exists())
            evidence = json.loads(
                (project / "papers/run/evidence.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["schema_version"], "evidence_bundle.v2")
            self.assertIn("evidence/results/metrics.json", evidence["result_file_refs"])
            self.assertTrue(evidence["public_evidence_files"])
            ledger = json.loads(
                (project / "papers/run/claims.json").read_text(encoding="utf-8")
            )
            self.assertTrue(ledger["claims"])
            self.assertTrue(ledger["claims"][0]["evidence_refs"])

    def test_writer_rejects_unexpandable_project_dir_without_runtime_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HTTPException) as raised:
                write_paper_artifacts(
                    self._config(tmp),
                    {
                        "project_id": "idea",
                        "project_name": "Idea",
                        "project_dir": "~enoch-user-that-should-not-exist/idea",
                    },
                    self._paper(),
                    force=True,
                )
            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("project_dir", str(raised.exception.detail))

    def test_writer_rejects_invalid_project_dir_without_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HTTPException) as raised:
                write_paper_artifacts(
                    self._config(tmp),
                    {
                        "project_id": "idea",
                        "project_name": "Idea",
                        "project_dir": "bad\0idea",
                    },
                    self._paper(),
                    force=True,
                )
            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("project_dir", str(raised.exception.detail))

    def test_evidence_bundle_public_paths_are_unique_after_sanitization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured result exists.\n", encoding="utf-8"
            )
            results = project / "results"
            results.mkdir()
            (results / "a?b.json").write_text('{"metric":1}\n', encoding="utf-8")
            (results / "a*b.json").write_text('{"metric":2}\n', encoding="utf-8")

            write_paper_artifacts(
                self._config(tmp),
                {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"},
                self._paper(),
                force=True,
            )

            evidence = json.loads(
                (project / "papers/run/evidence.json").read_text(encoding="utf-8")
            )
            paths = [item["path"] for item in evidence["public_evidence_files"]]
            assert len(paths) == len(set(paths))

    def test_evidence_bundle_redacts_secret_like_tokens_from_public_content(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            synthetic_token = "syn_" + "abcdefghijklmnopqrstuvwxyz1234567890"
            openai_key = "sk-proj-" + "abcdefghijklmnopqrstuvwxyz1234567890abcdefghijkl"
            secret_text = (
                f"Authorization: Bearer {synthetic_token}\n"
                f"OPENAI_API_KEY={openai_key}\n"
                "normal_metric=1.23\n"
            )
            (project / "run_notes.md").write_text(secret_text, encoding="utf-8")

            write_paper_artifacts(
                self._config(tmp),
                {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"},
                self._paper(),
                force=True,
            )

            evidence = json.loads(
                (project / "papers/run/evidence.json").read_text(encoding="utf-8")
            )
            run_notes = next(
                item
                for item in evidence["public_evidence_files"]
                if item["source_path"] == "run_notes.md"
            )
            content = run_notes["content"]
            self.assertIn("normal_metric=1.23", content)
            self.assertIn("Authorization: Bearer [REDACTED_TOKEN]", content)
            self.assertIn("OPENAI_API_KEY=[REDACTED_TOKEN]", content)
            self.assertNotIn("syn_abcdefghijklmnopqrstuvwxyz", content)
            self.assertNotIn("sk-proj-abcdefghijklmnopqrstuvwxyz", content)

    def test_evidence_bundle_excludes_raw_private_worker_metadata_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured result exists.\n", encoding="utf-8"
            )
            for rel in ("prompts", "scripts", "logs", ".enoch/state", ".enoch/logs"):
                directory = project / rel
                directory.mkdir(parents=True)
                (directory / "private.txt").write_text(
                    "PRIVATE_TOKEN=secret-value-123456789\n", encoding="utf-8"
                )
            (project / ".enoch").mkdir(exist_ok=True)
            (project / ".enoch" / "session.json").write_text(
                '{"token":"secret-value-123456789"}\n', encoding="utf-8"
            )

            write_paper_artifacts(
                self._config(tmp),
                {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"},
                self._paper(),
                force=True,
            )

            evidence = json.loads(
                (project / "papers/run/evidence.json").read_text(encoding="utf-8")
            )
            source_paths = {
                item["source_path"] for item in evidence["public_evidence_files"]
            }
            assert "run_notes.md" in source_paths
            assert not any(
                path.startswith(
                    ("prompts/", "scripts/", "logs/", ".enoch/state/", ".enoch/logs/")
                )
                for path in source_paths
            )
            assert ".enoch/session.json" not in source_paths

    def test_evidence_bundle_limits_large_source_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            large_text = "metric=1\n" * 20_000
            (project / "run_notes.md").write_text(large_text, encoding="utf-8")
            meta = write_paper_artifacts(
                self._config(tmp),
                {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"},
                self._paper(),
                force=True,
            )
            self.assertEqual(meta["provider"], "deterministic")
            evidence = json.loads(
                (project / "papers/run/evidence.json").read_text(encoding="utf-8")
            )
            run_notes = next(
                item
                for item in evidence["public_evidence_files"]
                if item["source_path"] == "run_notes.md"
            )
            inventory = next(
                item
                for item in evidence["file_inventory"]
                if item["source_path"] == "run_notes.md"
            )
            self.assertLessEqual(len(run_notes["content"].encode("utf-8")), 80_000)
            self.assertTrue(run_notes["truncated"])
            self.assertTrue(inventory["truncated"])
            self.assertEqual(inventory["bytes"], len(large_text.encode("utf-8")))

    def test_evidence_and_claim_metadata_redact_secret_like_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured result exists.\n", encoding="utf-8"
            )

            write_paper_artifacts(
                self._config(tmp),
                {
                    "project_id": "idea",
                    "project_name": "Idea",
                    "project_dir": "idea",
                    "evidence_sync": {
                        "error": "Authorization: Bearer syn_abcdefghijklmnopqrstuvwxyz1234567890"
                    },
                },
                self._paper(),
                force=True,
            )

            evidence_text = (project / "papers/run/evidence.json").read_text(
                encoding="utf-8"
            )
            claims_text = (project / "papers/run/claims.json").read_text(
                encoding="utf-8"
            )
            self.assertIn("Authorization: Bearer [REDACTED_TOKEN]", evidence_text)
            self.assertNotIn("syn_abcdefghijklmnopqrstuvwxyz", evidence_text)
            self.assertNotIn("syn_abcdefghijklmnopqrstuvwxyz", claims_text)

    def test_synthetic_writer_uses_openai_compatible_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            cfg = self._config(
                tmp,
                paper_writer_provider="synthetic.new",
                paper_writer_api_key="test-key",
            )

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b'{"id":"cmpl-test","choices":[{"message":{"content":"# Model Draft\\n\\nEvidence-grounded."}}]}'

            evidence_path = project / "papers/run/evidence.json"
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text('{"real": true}\n', encoding="utf-8")
            (project / "run_notes.md").write_text(
                "Evidence-grounded model draft completed with measured result files.\n",
                encoding="utf-8",
            )
            with patch(
                "enoch_control_plane.control_plane.paper_writer.request.urlopen",
                return_value=FakeResponse(),
            ) as urlopen:
                meta = write_paper_artifacts(
                    cfg,
                    {
                        "project_id": "idea",
                        "project_name": "Idea",
                        "project_dir": "idea",
                    },
                    self._paper(),
                    force=True,
                )
            self.assertIn(
                "evidence_bundle.v2", evidence_path.read_text(encoding="utf-8")
            )
            self.assertEqual(meta["provider"], "synthetic.new")
            self.assertEqual(meta["model"], "hf:zai-org/GLM-5.1")
            self.assertIn("/chat/completions", urlopen.call_args.args[0].full_url)
            payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
            prompt = payload["messages"][1]["content"]
            self.assertIn("Never write TODO", prompt)
            self.assertIn("Referenced artifacts", prompt)
            self.assertIn("Do not require a human reviewer", prompt)
            self.assertNotIn("Mark missing external references as TODO", prompt)
            self.assertIn(
                "# Model Draft", (project / "papers/run/paper.md").read_text()
            )

    def test_synthetic_writer_redacts_secret_like_tokens_from_provider_prompt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "SYNTHETIC_API_KEY=syn_abcdefghijklmnopqrstuvwxyz1234567890\n"
                "Measured throughput improved by 1.20x against baseline.\n",
                encoding="utf-8",
            )
            cfg = self._config(
                tmp,
                paper_writer_provider="synthetic.new",
                paper_writer_api_key="test-key",
            )

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b'{"id":"cmpl-test","choices":[{"message":{"content":"# Model Draft\n\nMeasured result."}}]}'

            with patch(
                "enoch_control_plane.control_plane.paper_writer.request.urlopen",
                return_value=FakeResponse(),
            ) as urlopen:
                write_paper_artifacts(
                    cfg,
                    {
                        "project_id": "idea",
                        "project_name": "Idea",
                        "project_dir": "idea",
                    },
                    self._paper(),
                    force=True,
                )

            payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
            prompt = payload["messages"][1]["content"]
            self.assertIn("Measured throughput improved", prompt)
            self.assertIn("SYNTHETIC_API_KEY=[REDACTED_TOKEN]", prompt)
            self.assertNotIn("syn_abcdefghijklmnopqrstuvwxyz", prompt)

    def test_synthetic_writer_redacts_secret_like_tokens_from_candidate_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured evidence exists.\n", encoding="utf-8"
            )
            cfg = self._config(
                tmp,
                paper_writer_provider="synthetic.new",
                paper_writer_api_key="test-key",
            )

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b'{"id":"cmpl-test","choices":[{"message":{"content":"# Model Draft\n\nMeasured result."}}]}'

            candidate = {
                "project_id": "idea",
                "project_name": "Idea",
                "project_dir": "idea",
                "source_payload_json": {
                    "operator_note": "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdefghijkl"
                },
            }
            with patch(
                "enoch_control_plane.control_plane.paper_writer.request.urlopen",
                return_value=FakeResponse(),
            ) as urlopen:
                write_paper_artifacts(cfg, candidate, self._paper(), force=True)

            payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
            prompt = payload["messages"][1]["content"]
            self.assertIn("OPENAI_API_KEY=[REDACTED_TOKEN]", prompt)
            self.assertNotIn("sk-proj-abcdefghijklmnopqrstuvwxyz", prompt)

    def test_synthetic_writer_serializes_datetime_candidate_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Evidence-grounded synthetic writer date serialization check.\n",
                encoding="utf-8",
            )
            cfg = self._config(
                tmp,
                paper_writer_provider="synthetic.new",
                paper_writer_api_key="test-key",
                paper_writer_fallback_enabled=False,
            )

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b'{"id":"cmpl-test","choices":[{"message":{"content":"# Model Draft\\n\\nEvidence-grounded."}}]}'

            candidate = {
                "project_id": "idea",
                "project_name": "Idea",
                "project_dir": "idea",
                "paper_review_item": {
                    "updated_at": datetime(2026, 5, 9, tzinfo=timezone.utc)
                },
            }
            with patch(
                "enoch_control_plane.control_plane.paper_writer.request.urlopen",
                return_value=FakeResponse(),
            ) as urlopen:
                meta = write_paper_artifacts(cfg, candidate, self._paper(), force=True)
            self.assertFalse(meta["fallback_used"])
            payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
            self.assertIn("2026-05-09", payload["messages"][1]["content"])

    def test_claim_ledger_requires_strong_evidence_refs_for_pass_status(self) -> None:
        paper = self._paper()
        evidence_bundle = {
            "public_evidence_files": [
                {
                    "path": "evidence/run_notes.md",
                    "source_path": "run_notes.md",
                    "sha256": "abc",
                    "content": "Only generic setup notes with no matching metrics.",
                }
            ]
        }
        markdown = "The experiment improved latency by 9.99x over the dense baseline."

        ledger = _build_claim_ledger_data(
            markdown, evidence_bundle, paper, writer_provider={"provider": "unit"}
        )

        self.assertEqual(ledger["ledger_status"], "claims_require_review")
        self.assertEqual(ledger["claims"][0]["support_status"], "weakly_supported")
        self.assertEqual(
            ledger["claims"][0]["evidence_refs"][0]["support_level"], "weak_context"
        )

    def test_synthetic_writer_rejects_non_http_provider_before_urlopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Fallback writer had local source evidence.\n", encoding="utf-8"
            )
            cfg = self._config(
                tmp,
                paper_writer_provider="synthetic.new",
                paper_writer_api_key="test-key",
                paper_writer_base_url="file:///etc/passwd",
                paper_writer_fallback_enabled=True,
            )

            def fake_urlopen(*_args, **_kwargs):
                raise AssertionError(
                    "urlopen should not run for unsafe paper writer URL"
                )

            with patch(
                "enoch_control_plane.control_plane.paper_writer.request.urlopen",
                side_effect=fake_urlopen,
            ):
                meta = write_paper_artifacts(
                    cfg,
                    {
                        "project_id": "idea",
                        "project_name": "Idea",
                        "project_dir": "idea",
                    },
                    self._paper(),
                    force=True,
                )
            self.assertTrue(meta["fallback_used"])
            self.assertIn(
                "paper writer provider url must use http or https",
                meta["fallback_reason"],
            )

    def test_write_files_rejects_empty_or_directory_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            for rel_path in ("", "."):
                with self.subTest(rel_path=rel_path):
                    with self.assertRaises(HTTPException):
                        _write_files(project, {rel_path: "bad"}, force=True)
            self.assertTrue(project.is_dir())

    def test_write_files_rejects_uninspectable_target_without_raw_permission_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            target = (project / "papers" / "run" / "paper.md").resolve()
            original_exists = Path.exists

            def fake_exists(path: Path) -> bool:
                if path == target:
                    raise PermissionError("denied")
                return original_exists(path)

            with patch.object(Path, "exists", fake_exists):
                with self.assertRaises(HTTPException) as raised:
                    _write_files(project, {"papers/run/paper.md": "new"}, force=True)

            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("paper path", str(raised.exception.detail))
            self.assertFalse((project / "papers/run/paper.md").exists())

    def test_write_files_preserves_existing_artifact_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            target = project / "papers" / "run" / "paper.md"
            target.parent.mkdir(parents=True)
            target.write_text("old", encoding="utf-8")

            with patch(
                "enoch_control_plane.control_plane.paper_writer.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaises(OSError):
                    _write_files(project, {"papers/run/paper.md": "new"}, force=True)

            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(target.parent.glob(".paper.md.*.tmp")), [])

    def test_backfill_rejects_invalid_manifest_path_without_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured useful evidence.\n", encoding="utf-8"
            )
            paper_dir = project / "papers" / "run"
            paper_dir.mkdir(parents=True)
            (paper_dir / "paper.md").write_text(
                "Measured useful evidence.\n", encoding="utf-8"
            )
            paper = self._paper().model_copy(
                update={"manifest_path": "bad\0manifest.json"}
            )

            with self.assertRaises(HTTPException) as raised:
                backfill_paper_evidence_artifacts(
                    self._config(tmp),
                    {
                        "project_id": "idea",
                        "project_name": "Idea",
                        "project_dir": "idea",
                    },
                    paper,
                    force=True,
                )

            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("paper path", str(raised.exception.detail))

    def test_write_paper_artifacts_blocks_unreadable_source_evidence_without_partial_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured evidence exists.\n", encoding="utf-8"
            )

            with patch(
                "enoch_control_plane.control_plane.paper_writer._read_evidence_preview",
                side_effect=PermissionError("denied"),
            ):
                with self.assertRaises(HTTPException) as raised:
                    write_paper_artifacts(
                        self._config(tmp),
                        {
                            "project_id": "idea",
                            "project_name": "Idea",
                            "project_dir": "idea",
                        },
                        self._paper(),
                        force=True,
                    )

            self.assertEqual(raised.exception.status_code, 424)
            self.assertIn("source evidence", str(raised.exception.detail))
            self.assertFalse((project / "papers/run/paper.md").exists())
            self.assertFalse((project / "papers/run/evidence.json").exists())

    def test_backfill_blocks_uninspectable_paper_markdown_without_partial_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured useful evidence.\n", encoding="utf-8"
            )
            paper_path = project / "papers" / "run" / "paper.md"
            paper_path.parent.mkdir(parents=True)
            paper_path.write_text("Measured useful evidence.\n", encoding="utf-8")
            resolved_paper_path = paper_path.resolve()
            original_exists = Path.exists

            def fake_exists(path: Path) -> bool:
                if path == resolved_paper_path:
                    raise PermissionError("denied")
                return original_exists(path)

            with patch.object(Path, "exists", fake_exists):
                with self.assertRaises(HTTPException) as raised:
                    backfill_paper_evidence_artifacts(
                        self._config(tmp),
                        {
                            "project_id": "idea",
                            "project_name": "Idea",
                            "project_dir": "idea",
                        },
                        self._paper(),
                        force=True,
                    )

            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("paper markdown", str(raised.exception.detail))
            self.assertFalse((project / "papers/run/evidence.json").exists())
            self.assertFalse((project / "papers/run/claims.json").exists())

    def test_backfill_blocks_uninspectable_existing_manifest_before_writing_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured useful evidence.\n", encoding="utf-8"
            )
            paper_dir = project / "papers" / "run"
            paper_dir.mkdir(parents=True)
            (paper_dir / "paper.md").write_text(
                "Measured useful evidence.\n", encoding="utf-8"
            )
            manifest_path = (paper_dir / "manifest.json").resolve()
            manifest_path.write_text('{"existing": true}\n', encoding="utf-8")
            original_exists = Path.exists

            def fake_exists(path: Path) -> bool:
                if path == manifest_path:
                    raise PermissionError("denied")
                return original_exists(path)

            with patch.object(Path, "exists", fake_exists):
                with self.assertRaises(HTTPException) as raised:
                    backfill_paper_evidence_artifacts(
                        self._config(tmp),
                        {
                            "project_id": "idea",
                            "project_name": "Idea",
                            "project_dir": "idea",
                        },
                        self._paper(),
                        force=True,
                    )

            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("paper manifest", str(raised.exception.detail))
            self.assertFalse((paper_dir / "evidence.json").exists())
            self.assertFalse((paper_dir / "claims.json").exists())
            self.assertEqual(
                (paper_dir / "manifest.json").read_text(encoding="utf-8"),
                '{"existing": true}\n',
            )

    def test_backfill_replaces_malformed_existing_manifest_without_blocking_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured useful evidence.\n", encoding="utf-8"
            )
            paper_dir = project / "papers" / "run"
            paper_dir.mkdir(parents=True)
            (paper_dir / "paper.md").write_text(
                "Measured useful evidence.\n", encoding="utf-8"
            )
            (paper_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

            result = backfill_paper_evidence_artifacts(
                self._config(tmp),
                {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"},
                self._paper(),
                force=True,
            )

            assert result["evidence_file_count"] >= 1
            manifest = json.loads(
                (paper_dir / "manifest.json").read_text(encoding="utf-8")
            )
            assert manifest["evidence_backfilled"] is True
            assert manifest["paper_id"] == self._paper().paper_id

    def test_synthetic_writer_blocks_uninspectable_existing_evidence_without_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Measured useful evidence.\n", encoding="utf-8"
            )
            evidence_path = project / "papers" / "run" / "evidence.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text('{"existing": true}\n', encoding="utf-8")
            cfg = self._config(
                tmp,
                paper_writer_provider="synthetic.new",
                paper_writer_api_key="test-key",
                paper_writer_fallback_enabled=True,
            )

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b'{"id":"cmpl-test","choices":[{"message":{"content":"# Model Draft\\n\\nEvidence-grounded."}}]}'

            original_exists = Path.exists
            resolved_evidence_path = evidence_path.resolve()

            def fake_exists(path: Path) -> bool:
                if path == resolved_evidence_path:
                    raise PermissionError("denied")
                return original_exists(path)

            with patch(
                "enoch_control_plane.control_plane.paper_writer.request.urlopen",
                return_value=FakeResponse(),
            ):
                with patch.object(Path, "exists", fake_exists):
                    with self.assertRaises(HTTPException) as raised:
                        write_paper_artifacts(
                            cfg,
                            {
                                "project_id": "idea",
                                "project_name": "Idea",
                                "project_dir": "idea",
                            },
                            self._paper(),
                            force=True,
                        )

            self.assertEqual(raised.exception.status_code, 400)
            self.assertIn("paper evidence", str(raised.exception.detail))
            self.assertEqual(
                evidence_path.read_text(encoding="utf-8"), '{"existing": true}\n'
            )
            self.assertFalse((project / "papers/run/paper.md").exists())

    def test_synthetic_writer_falls_back_without_key_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "idea"
            project.mkdir(parents=True)
            (project / "run_notes.md").write_text(
                "Fallback writer had local source evidence.\n", encoding="utf-8"
            )
            cfg = self._config(
                tmp,
                paper_writer_provider="synthetic.new",
                paper_writer_api_key="",
                paper_writer_fallback_enabled=True,
            )
            meta = write_paper_artifacts(
                cfg,
                {"project_id": "idea", "project_name": "Idea", "project_dir": "idea"},
                self._paper(),
                force=True,
            )
            self.assertTrue(meta["fallback_used"])
            self.assertTrue((project / "papers/run/paper.md").exists())

    def test_sentence_claims_keeps_hash_prefixed_non_heading_lines(self) -> None:
        md = """
# Heading
#1 The result improved 99% in throughput versus baseline with observed evidence support.
#claim The result increased latency by 20ms in a tested run with baseline comparison.

"""
        claims = _sentence_claims(md)
        joined = " ".join(claims).lower()
        self.assertIn("99%", joined)
        self.assertIn("20ms", joined)
        self.assertNotIn("heading", joined)

    def test_sentence_claims_uses_safe_detection_and_extracts_signals(self) -> None:
        """_sentence_claims must extract claims using safe keyword matching (no ReDoS regex)."""
        md = """
# Header

Some sentence without signal.

The result showed 42% improvement in latency and throughput.

This is a long sentence that mentions evidence and was validated in testing with positive support from the baseline run.

"""
        claims = _sentence_claims(md)
        self.assertGreater(len(claims), 0)
        joined = " ".join(claims).lower()
        self.assertIn("result", joined)
        self.assertIn("42", joined)  # digit trigger
        self.assertIn("improvement", joined)
        # Should not include the header or non-signal
        self.assertNotIn("header", joined)


if __name__ == "__main__":
    unittest.main()
