import json
from argparse import Namespace

import pytest

from scripts import apply_supabase_runtime_cutover as cutover


def _args(
    tmp_path,
    *,
    database_url: str = "postgresql://user:secret@example.test/db",
    dry_run: bool = True,
) -> Namespace:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"state_dir": "/var/lib/enoch-control-plane"}) + "\n",
        encoding="utf-8",
    )
    return Namespace(
        config=str(config),
        env_file=str(tmp_path / "supabase.env"),
        service="enoch-control-plane.service",
        control_url="http://127.0.0.1:8787",
        token_file=str(tmp_path / "token.txt"),
        database_url=database_url,
        dry_run=dry_run,
        no_systemd=True,
    )


def test_cutover_dry_run_requires_passing_preflight_and_does_not_write_config(
    tmp_path, monkeypatch
) -> None:
    calls = []
    monkeypatch.setattr(
        cutover, "_run_preflight", lambda *args: calls.append(args) or 0
    )
    args = _args(tmp_path, dry_run=True)

    result = cutover.cutover(args)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["database_url"] == "postgresql://user:***@example.test/db"
    assert json.loads((tmp_path / "config.json").read_text()) == {
        "state_dir": "/var/lib/enoch-control-plane"
    }
    assert not (tmp_path / "supabase.env").exists()
    assert len(calls) == 1


def test_cutover_redacts_query_passwords_and_fragments() -> None:
    assert (
        cutover._redact_url(
            "postgresql://db.example/postgres?user=svc&password=secret#frag"
        )
        == "postgresql://db.example/postgres?user=svc&password=***"
    )
    assert (
        cutover._redact_url(
            "postgresql://svc:secret@db.example:5432/postgres?sslpassword=secret"
        )
        == "postgresql://svc:***@db.example:5432/postgres?sslpassword=***"
    )


def test_cutover_fails_closed_without_database_url(tmp_path) -> None:
    args = _args(tmp_path, database_url="")

    with pytest.raises(RuntimeError, match="missing Supabase Postgres URL"):
        cutover.cutover(args)


def test_cutover_rolls_back_config_and_env_on_post_preflight_failure(
    tmp_path, monkeypatch
) -> None:
    outcomes = iter([0, 1])
    monkeypatch.setattr(cutover, "_run_preflight", lambda *args: next(outcomes))
    args = _args(tmp_path, dry_run=False)

    with pytest.raises(RuntimeError, match="preflight failed after cutover"):
        cutover.cutover(args)

    assert json.loads((tmp_path / "config.json").read_text()) == {
        "state_dir": "/var/lib/enoch-control-plane"
    }
    assert not (tmp_path / "supabase.env").exists()
    assert list(tmp_path.glob("config.json.backup.*"))


def test_cutover_rolls_back_systemd_dropin_after_post_preflight_failure(
    tmp_path, monkeypatch
) -> None:
    outcomes = iter([0, 1])
    dropin = (
        tmp_path / "systemd" / "enoch-control-plane.service.d" / "10-supabase-env.conf"
    )

    def ensure_dropin(_service, env_file):
        dropin.parent.mkdir(parents=True)
        dropin.write_text(f"[Service]\nEnvironmentFile={env_file}\n", encoding="utf-8")
        return dropin

    monkeypatch.setattr(cutover.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cutover, "_run_preflight", lambda *args: next(outcomes))
    monkeypatch.setattr(cutover, "_ensure_systemd_env_file", ensure_dropin)
    monkeypatch.setattr(cutover, "_systemctl", lambda _args: None)
    monkeypatch.setattr(cutover, "_service_active", lambda _service: True)
    monkeypatch.setattr(cutover, "_wait_control_plane_ready", lambda *_args: None)
    args = _args(tmp_path, dry_run=False)
    args.no_systemd = False

    with pytest.raises(RuntimeError, match="preflight failed after cutover"):
        cutover.cutover(args)

    assert not (tmp_path / "supabase.env").exists()
    assert not dropin.exists()
