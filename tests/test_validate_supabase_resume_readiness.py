from pathlib import Path

from scripts.validate_supabase_resume_readiness import DEFAULT_CONTROL_PLANE_URL


def test_default_control_plane_url_uses_https_for_lab_host() -> None:
    assert DEFAULT_CONTROL_PLANE_URL == "https://192.168.1.166:8787"


def test_main_control_url_default_has_no_cleartext_http_fallback() -> None:
    source = Path("scripts/validate_supabase_resume_readiness.py").read_text(
        encoding="utf-8"
    )
    main_block = source.split("def main()", 1)[1]
    assert '"http://' not in main_block


def test_ssh_timer_check_uses_pinned_known_hosts_and_remote_helper(monkeypatch) -> None:
    from scripts import validate_supabase_resume_readiness as readiness

    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = "disabled\n--active--\ninactive\n"

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)

    result = readiness._run_ssh_timer_check("enoch-control.example")

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:7] == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=/etc/enoch/known_hosts",
    ]
    assert cmd[-2:] == ["enoch-control.example", "/opt/enoch/scripts/timer_check.sh"]
    assert not any(";" in part or "||" in part or "systemctl" in part for part in cmd)
    assert result["enabled"] == ["disabled"]
    assert result["active"] == ["inactive"]
