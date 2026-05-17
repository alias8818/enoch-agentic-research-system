from __future__ import annotations

import json
from pathlib import Path

from scripts import agentic_property_testing
from scripts.agentic_property_testing import execute_proposals, generate_provider_proposal, run_autonomous_loop, synthetic_budget_preflight, write_prompt


def test_agentic_property_testing_writes_llm_prompt(tmp_path: Path) -> None:
    repo = tmp_path
    target = repo / "sample.py"
    target.write_text("def identity(value):\n    return value\n", encoding="utf-8")
    output = repo / "prompt.md"

    write_prompt(repo, target, output, max_chars=1000)

    text = output.read_text(encoding="utf-8")
    assert "Agentic property-based testing request" in text
    assert "def identity" in text
    assert "hypothesis" in text.lower()


def test_agentic_property_testing_records_counterexample_report(tmp_path: Path) -> None:
    repo = tmp_path
    module = repo / "buggy_module.py"
    module.write_text("def absolute(value: int) -> int:\n    return value\n", encoding="utf-8")
    proposals = repo / "proposals.json"
    proposals.write_text(
        json.dumps(
            {
                "tests": [
                    {
                        "name": "absolute_is_non_negative",
                        "rationale": "absolute values should be non-negative",
                        "code": "from hypothesis import given, strategies as st\nfrom buggy_module import absolute\n\n@given(st.integers(max_value=-1))\ndef test_absolute_is_non_negative(value):\n    assert absolute(value) >= 0\n",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = execute_proposals(repo, proposals, repo / "reports")

    assert result["status"] == "counterexample_found"
    assert "agent" in result["next_action"]
    assert "human" not in result["next_action"].lower()
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "absolute_is_non_negative" in report
    assert "Exit code: `1`" in report
    assert "No operator action required" in report
    assert Path(result["reproducer_path"]).is_file()


def test_agentic_property_testing_classifies_collection_errors_as_proposal_error(tmp_path: Path) -> None:
    repo = tmp_path
    proposals = repo / "proposals.json"
    proposals.write_text(
        json.dumps(
            {
                "tests": [
                    {
                        "name": "invalid_collection_time_api",
                        "rationale": "invalid generated test code should not count as a product counterexample",
                        "code": "from hypothesis import given, strategies as st\n\n@given(st.paths())\ndef test_invalid(value):\n    assert value\n",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = execute_proposals(repo, proposals, repo / "reports")

    assert result["status"] == "proposal_error"
    assert result["agentic_terminal"] is True
    assert "regenerate" in result["next_action"]
    assert "human" not in result["next_action"].lower()
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Agentic PBT report - proposal_error" in report
    assert "Exit code: `2`" in report
    assert "No operator action required" in report
    assert Path(result["reproducer_path"]).is_file()



def test_agentic_property_testing_classifies_pytest_invocation_errors() -> None:
    assert agentic_property_testing._execution_status(4, "ERROR: file or directory not found: -q") == "execution_error"
    assert agentic_property_testing._execution_status(1, "/usr/bin/python3: No module named pytest") == "execution_error"
    assert "agent" in agentic_property_testing._agentic_next_action("execution_error")


def test_agentic_property_testing_main_strips_passthrough_separator(tmp_path: Path, capsys) -> None:
    module = tmp_path / "sample_module.py"
    module.write_text("def identity(value):\n    return value\n", encoding="utf-8")
    proposals = tmp_path / "proposal.json"
    proposals.write_text(
        json.dumps({"tests": [{"name": "identity", "rationale": "identity", "code": "from sample_module import identity\n\ndef test_identity():\n    assert identity('x') == 'x'\n"}]}),
        encoding="utf-8",
    )

    code = agentic_property_testing.main([
        "--repo-root",
        str(tmp_path),
        "--target",
        str(module),
        "--proposal-file",
        str(proposals),
        "--execute-proposals",
        "--",
        "-q",
    ])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "no_counterexample"

def test_agentic_property_testing_autonomous_loop_retries_proposal_errors(tmp_path: Path) -> None:
    repo = tmp_path
    module = repo / "sample_module.py"
    module.write_text("def identity(value):\n    return value\n", encoding="utf-8")
    invalid = repo / "invalid.json"
    invalid.write_text(
        json.dumps({"tests": [{"name": "bad_api", "rationale": "bad generated API", "code": "from hypothesis import given, strategies as st\n\n@given(st.paths())\ndef test_bad(value):\n    assert value\n"}]}),
        encoding="utf-8",
    )
    valid = repo / "valid.json"
    valid.write_text(
        json.dumps({"tests": [{"name": "identity_roundtrip", "rationale": "identity returns input", "code": "from hypothesis import given, strategies as st\nfrom sample_module import identity\n\n@given(st.text())\ndef test_identity_roundtrip(value):\n    assert identity(value) == value\n"}]}),
        encoding="utf-8",
    )

    result = run_autonomous_loop(repo, module, [invalid, valid], repo / "reports", max_attempts=3)

    assert result["status"] == "no_counterexample"
    assert result["attempt_count"] == 2
    assert result["attempts"][0]["status"] == "proposal_error"
    assert result["attempts"][1]["status"] == "no_counterexample"
    assert result["attempts"][0]["report_path"] != result["attempts"][1]["report_path"]
    assert "human" not in json.dumps(result).lower()
    loop_report = Path(result["loop_report_path"]).read_text(encoding="utf-8")
    assert "No operator action required" in loop_report


def test_agentic_property_testing_autonomous_loop_max_attempt_exhaustion(tmp_path: Path) -> None:
    repo = tmp_path
    target = repo / "sample.py"
    target.write_text("def identity(value):\n    return value\n", encoding="utf-8")
    invalid = repo / "invalid.json"
    invalid.write_text(
        json.dumps({"tests": [{"name": "bad_api", "rationale": "bad generated API", "code": "from hypothesis import given, strategies as st\n\n@given(st.paths())\ndef test_bad(value):\n    assert value\n"}]}),
        encoding="utf-8",
    )

    result = run_autonomous_loop(repo, target, [invalid], repo / "reports", max_attempts=1)

    assert result["status"] == "max_attempts_exhausted"
    assert result["agentic_terminal"] is True
    assert "regenerate" in result["next_action"]
    assert "human" not in json.dumps(result).lower()


def test_agentic_property_testing_synthetic_budget_preflight_supports_no_auth_proxy(monkeypatch) -> None:
    calls: list[tuple[str, str, int]] = []

    def fake_fetch_json(url: str, *, api_key: str = "", timeout: int) -> dict:
        calls.append((url, api_key, timeout))
        return {
            "weeklyTokenLimit": {"remainingCredits": "$10.00"},
            "rollingFiveHourLimit": {"remaining": 50, "max": 50, "limited": False},
            "subscription": {"limit": 100, "requests": 0},
        }

    monkeypatch.setattr(agentic_property_testing.research_provider_budget, "fetch_json", fake_fetch_json)

    result = synthetic_budget_preflight(
        base_url="https://synthetic.int.exe.xyz",
        api_key="should-not-be-used",
        no_auth=True,
        timeout=7,
        estimated_requests=1,
        reserve_requests=1,
        min_remaining_credits=1,
        min_rolling_remaining=1,
    )

    assert result["ok"] is True
    assert result["auth_mode"] == "exe_http_proxy"
    assert calls == [("https://synthetic.int.exe.xyz/v2/quotas", "", 7)]


def test_agentic_property_testing_provider_proposal_writes_json(monkeypatch, tmp_path: Path) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            content = json.dumps({"tests": [{"name": "sample", "rationale": "r", "code": "def test_sample(): assert True"}]})
            return json.dumps({"id": "resp-1", "choices": [{"message": {"content": content}}]}).encode()

    seen_headers = {}

    def fake_urlopen(req, timeout: int):
        seen_headers.update(dict(req.header_items()))
        assert timeout == 11
        return FakeResponse()

    monkeypatch.setattr(agentic_property_testing.urllib.request, "urlopen", fake_urlopen)
    output = tmp_path / "proposal.json"

    result = generate_provider_proposal(
        prompt_text="prompt",
        output=output,
        openai_base_url="https://synthetic.int.exe.xyz/openai/v1",
        model="hf:zai-org/GLM-5.1",
        api_key="",
        no_auth=True,
        temperature=0.1,
        max_tokens=100,
        timeout=11,
    )

    assert result["ok"] is True
    assert result["proposal_file"] == str(output)
    assert json.loads(output.read_text(encoding="utf-8"))["tests"][0]["name"] == "sample"
    assert "Authorization" not in seen_headers


def test_agentic_property_testing_provider_proposal_rejects_unsafe_url(monkeypatch, tmp_path: Path) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise AssertionError("urlopen should not run for unsafe provider URL")

    monkeypatch.setattr(agentic_property_testing.urllib.request, "urlopen", fake_urlopen)

    try:
        generate_provider_proposal(
            prompt_text="prompt",
            output=tmp_path / "proposal.json",
            openai_base_url="file:///tmp/provider",
            model="hf:zai-org/GLM-5.1",
            api_key="",
            no_auth=True,
            temperature=0.1,
            max_tokens=100,
            timeout=11,
        )
    except ValueError as exc:
        assert "agentic pbt provider url must use http or https" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unsafe provider URL rejection")


def test_agentic_property_testing_provider_budget_failure_fails_closed(monkeypatch, tmp_path: Path, capsys) -> None:
    target = tmp_path / "sample.py"
    target.write_text("def identity(value):\n    return value\n", encoding="utf-8")

    def fail_budget(**_kwargs):
        raise TimeoutError("quota timeout")

    monkeypatch.setattr(agentic_property_testing, "synthetic_budget_preflight", fail_budget)

    code = agentic_property_testing.main([
        "--repo-root",
        str(tmp_path),
        "--target",
        str(target),
        "--generate-provider-proposal",
        "--provider-no-auth",
    ])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "provider_budget_blocked"
    assert payload["agentic_terminal"] is True
    assert "quota timeout" in payload["failures"][0]
    assert "human" not in json.dumps(payload).lower()


def test_agentic_property_testing_provider_generation_failure_fails_closed(monkeypatch, tmp_path: Path, capsys) -> None:
    target = tmp_path / "sample.py"
    target.write_text("def identity(value):\n    return value\n", encoding="utf-8")

    monkeypatch.setattr(agentic_property_testing, "synthetic_budget_preflight", lambda **_kwargs: {"ok": True})

    def fail_generate(**_kwargs):
        raise TimeoutError("generation timeout")

    monkeypatch.setattr(agentic_property_testing, "generate_provider_proposal", fail_generate)

    code = agentic_property_testing.main([
        "--repo-root",
        str(tmp_path),
        "--target",
        str(target),
        "--generate-provider-proposal",
        "--provider-no-auth",
    ])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "provider_generation_failed"
    assert payload["agentic_terminal"] is True
    assert "generation timeout" in payload["failures"][0]
    assert "human" not in json.dumps(payload).lower()
