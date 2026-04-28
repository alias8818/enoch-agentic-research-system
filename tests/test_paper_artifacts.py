from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from omx_wake_gate.app import _resolve_project_relative_path, _write_text


class PaperArtifactPathTests(unittest.TestCase):
    def test_resolves_safe_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp).resolve()
            resolved = _resolve_project_relative_path(project_dir, "papers/run-1/paper.md")
            self.assertEqual(resolved, project_dir / "papers" / "run-1" / "paper.md")

    def test_rejects_absolute_and_parent_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp).resolve()
            for unsafe in ("/tmp/paper.md", "../paper.md", "papers/../paper.md", ""):
                with self.subTest(unsafe=unsafe):
                    with self.assertRaises(HTTPException):
                        _resolve_project_relative_path(project_dir, unsafe)

    def test_write_text_respects_overwrite_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.md"
            _write_text(path, "one", overwrite=False)
            with self.assertRaises(HTTPException):
                _write_text(path, "two", overwrite=False)
            _write_text(path, "two", overwrite=True)
            self.assertEqual(path.read_text(), "two")

    def test_read_endpoint_uses_same_safe_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp).resolve()
            safe = _resolve_project_relative_path(project_dir, "papers/run-1/evidence_bundle.json")
            _write_text(safe, "{}", overwrite=False)
            self.assertEqual(safe.read_text(), "{}")
            with self.assertRaises(HTTPException):
                _resolve_project_relative_path(project_dir, "papers/run-1/../../secret.txt")


if __name__ == "__main__":
    unittest.main()
