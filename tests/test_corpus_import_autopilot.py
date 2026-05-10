from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "enoch_corpus_import_autopilot.py"
spec = importlib.util.spec_from_file_location("enoch_corpus_import_autopilot", MODULE_PATH)
assert spec and spec.loader
autopilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(autopilot)


def test_clean_noop_dry_run_is_successful_timer_idle():
    payload = {"failed": 0, "imported": 0, "updated": 0, "errors": [], "seen": 384, "skipped": 384}
    assert autopilot._is_clean_noop_dry_run(payload) is True


def test_failed_or_error_dry_run_is_not_clean_noop():
    assert autopilot._is_clean_noop_dry_run({"failed": 1, "imported": 0, "updated": 0, "errors": []}) is False
    assert autopilot._is_clean_noop_dry_run({"failed": 0, "imported": 0, "updated": 0, "errors": ["bad"]}) is False
