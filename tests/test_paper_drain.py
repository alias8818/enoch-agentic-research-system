from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import Mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "deploy" / "enoch_paper_drain_until_noop.py"
)
spec = importlib.util.spec_from_file_location(
    "enoch_paper_drain_until_noop", MODULE_PATH
)
assert spec and spec.loader
paper_drain = importlib.util.module_from_spec(spec)
sys.modules["enoch_paper_drain_until_noop"] = paper_drain
spec.loader.exec_module(paper_drain)


def test_paper_drain_skips_before_draft_loop_during_control_hold(
    monkeypatch, capsys
) -> None:
    client = Mock()
    client.get.return_value = (
        200,
        {
            "flags": {
                "queue_paused": True,
                "maintenance_mode": True,
                "pause_reason": "operator maintenance",
            }
        },
    )
    settings = paper_drain.DrainSettings(
        max_runs=25,
        fail_limit=3,
        sleep_sec=0,
        rewrite_new=True,
        requested_by="pytest",
        client=client,
    )

    monkeypatch.setenv("ENOCH_ENABLE_PAPER_DRAIN", "1")
    monkeypatch.setattr(paper_drain, "_load_drain_settings", lambda: settings)

    drain_loop_calls = 0

    def _drain_loop_spy(_settings):  # noqa: ANN001 - verifies branch selection only
        nonlocal drain_loop_calls
        drain_loop_calls += 1
        return 0

    monkeypatch.setattr(
        paper_drain,
        "_run_drain_loop",
        _drain_loop_spy,
    )

    assert paper_drain.main() == 0

    client.get.assert_called_once_with("/control/api/status")
    client.post.assert_not_called()
    assert drain_loop_calls == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "skipped"
    assert payload["hold_state"]["queue_paused"] is True
    assert payload["hold_state"]["maintenance_mode"] is True
