#!/usr/bin/env python3
"""Safely switch the live control-plane runtime to the Supabase backend.

Run this on the control-plane host after `validate_supabase_runtime_cutover.py`
passes. The script is fail-closed and reversible:

1. require root (unless --no-systemd is used for local tests),
2. require a Supabase Postgres URL,
3. run read-only parity preflight before touching runtime config,
4. back up the existing JSON config and optional env file,
5. write `control_plane_store_backend=supabase` and install a root-only env file,
6. restart the service,
7. run the same preflight again,
8. roll back config/env/service if any post-switch check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path("/etc/enoch-control-plane/config.json")
DEFAULT_ENV = Path("/etc/enoch-control-plane/postgres.env")
DEFAULT_SERVICE = "enoch-control-plane.service"
DEFAULT_CONTROL_URL = "http://127.0.0.1:8787"


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check
    )


def _redact_url(url: str) -> str:
    parsed = urlsplit(url)
    sensitive_query_keys = {
        "password",
        "pass",
        "pwd",
        "token",
        "apikey",
        "api_key",
        "sslpassword",
        "sslcert",
        "sslkey",
    }
    redacted_query = ""
    if parsed.query:
        parts = []
        for item in parsed.query.split("&"):
            key, sep, _ = item.partition("=")
            if key.lower() in sensitive_query_keys:
                parts.append(f"{key}{sep}***" if sep else key)
            else:
                parts.append(item)
        redacted_query = "&".join(parts)
    if not parsed.hostname or "@" not in parsed.netloc:
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, redacted_query, "")
        )
    auth = "***"
    if parsed.username:
        auth = f"{parsed.username}:***"
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit(
        (parsed.scheme, f"{auth}@{host}", parsed.path, redacted_query, "")
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copymode(path, tmp)
    os.replace(tmp, path)


def _write_env_file(path: Path, database_url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(f"ENOCH_SUPABASE_DATABASE_URL={database_url}\n", encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


def _ensure_systemd_env_file(service: str, env_file: Path) -> Path:
    dropin_dir = Path("/etc/systemd/system") / f"{service}.d"
    dropin_dir.mkdir(parents=True, exist_ok=True)
    dropin = dropin_dir / "10-supabase-env.conf"
    dropin.write_text(f"[Service]\nEnvironmentFile={env_file}\n", encoding="utf-8")
    return dropin


class CutoverSwitchError(RuntimeError):
    def __init__(self, message: str, *, dropin: Path | None = None) -> None:
        super().__init__(message)
        self.dropin = dropin


def _run_preflight(control_url: str, token_file: str, database_url: str) -> int:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from scripts.validate_supabase_runtime_cutover import main as preflight_main

    old_argv = sys.argv[:]
    old_env = os.environ.copy()
    try:
        os.environ["ENOCH_SUPABASE_DATABASE_URL"] = database_url
        sys.argv = [
            "validate_supabase_runtime_cutover.py",
            "--control-url",
            control_url,
            "--token-file",
            token_file,
        ]
        return preflight_main()
    finally:
        sys.argv = old_argv
        os.environ.clear()
        os.environ.update(old_env)


def _systemctl(args: list[str]) -> None:
    _run(["systemctl", *args])


def _service_active(service: str) -> bool:
    return (
        _run(["systemctl", "is-active", service], check=False).stdout.strip()
        == "active"
    )


def _load_token(path: str) -> str:
    explicit = os.environ.get("ENOCH_CONTROL_PLANE_TOKEN", "").strip()
    if explicit:
        return explicit
    token_path = Path(path)
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()
    return ""


def _wait_control_plane_ready(
    control_url: str, token_file: str, *, timeout_seconds: float = 45.0
) -> None:
    token = _load_token(token_file)
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(f"{control_url.rstrip('/')}/control/state")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310 - operator-provided LAN URL
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - operational wait loop.
            last_error = exc
        time.sleep(1)
    detail = f": {type(last_error).__name__}: {last_error}" if last_error else ""
    raise RuntimeError(
        f"control plane did not become HTTP-ready within {timeout_seconds:.0f}s{detail}"
    )


def _require_database_url(args: argparse.Namespace) -> str:
    database_url = args.database_url or os.environ.get(
        "ENOCH_SUPABASE_DATABASE_URL", ""
    )
    if not database_url.strip():
        raise RuntimeError(
            "missing Supabase Postgres URL; pass --database-url or set ENOCH_SUPABASE_DATABASE_URL"
        )
    return database_url


def _require_cutover_prerequisites(
    args: argparse.Namespace,
    config_path: Path,
    database_url: str,
    token_file: str,
) -> None:
    if not config_path.exists():
        raise RuntimeError(f"config file not found: {config_path}")
    if not args.no_systemd and hasattr(os, "geteuid") and os.geteuid() != 0:
        raise RuntimeError(
            "must run as root for systemd cutover; use --no-systemd only for local tests"
        )
    preflight_rc = _run_preflight(args.control_url, token_file, database_url)
    if preflight_rc != 0:
        raise RuntimeError(
            f"preflight failed before cutover with exit code {preflight_rc}"
        )


def _dry_run_cutover_result(database_url: str) -> dict[str, Any]:
    return {
        "ok": True,
        "dry_run": True,
        "database_url": _redact_url(database_url),
        "would_set_backend": "supabase",
    }


def _backup_cutover_files(
    config_path: Path, env_path: Path, stamp: str
) -> tuple[Path, Path | None]:
    config_backup = config_path.with_name(f"{config_path.name}.backup.{stamp}")
    shutil.copy2(config_path, config_backup)
    env_backup = None
    if env_path.exists():
        env_backup = env_path.with_name(f"{env_path.name}.backup.{stamp}")
        shutil.copy2(env_path, env_backup)
    return config_backup, env_backup


def _perform_cutover_switch(
    args: argparse.Namespace,
    *,
    config_path: Path,
    env_path: Path,
    database_url: str,
    token_file: str,
) -> Path | None:
    config = _load_json(config_path)
    config["control_plane_store_backend"] = "supabase"
    config["supabase_database_url"] = ""
    _atomic_write_json(config_path, config)
    _write_env_file(env_path, database_url)
    dropin = None
    try:
        if not args.no_systemd:
            dropin = _ensure_systemd_env_file(args.service, env_path)
            _systemctl(["daemon-reload"])
            _systemctl(["restart", args.service])
            if not _service_active(args.service):
                raise RuntimeError(f"service did not become active: {args.service}")
            _wait_control_plane_ready(args.control_url, token_file)
        post_rc = _run_preflight(args.control_url, token_file, database_url)
        if post_rc != 0:
            raise RuntimeError(
                f"preflight failed after cutover with exit code {post_rc}"
            )
    except Exception as exc:
        raise CutoverSwitchError(str(exc), dropin=dropin) from exc
    return dropin


def _rollback_cutover_switch(
    args: argparse.Namespace,
    *,
    config_path: Path,
    env_path: Path,
    config_backup: Path,
    env_backup: Path | None,
    dropin: Path | None,
) -> None:
    shutil.copy2(config_backup, config_path)
    if env_backup:
        shutil.copy2(env_backup, env_path)
    elif env_path.exists():
        env_path.unlink()
    if not args.no_systemd:
        if dropin and dropin.exists():
            dropin.unlink()
        _systemctl(["daemon-reload"])
        _systemctl(["restart", args.service])


def _cutover_success_result(
    database_url: str,
    config_backup: Path,
    env_path: Path,
    env_backup: Path | None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "dry_run": False,
        "backend": "supabase",
        "config_backup": str(config_backup),
        "env_file": str(env_path),
        "env_backup": str(env_backup) if env_backup else "",
        "database_url": _redact_url(database_url),
    }


def cutover(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config)
    env_path = Path(args.env_file)
    token_file = str(args.token_file)
    database_url = _require_database_url(args)
    _require_cutover_prerequisites(args, config_path, database_url, token_file)
    if args.dry_run:
        return _dry_run_cutover_result(database_url)

    stamp = _timestamp()
    config_backup, env_backup = _backup_cutover_files(config_path, env_path, stamp)
    dropin = None
    try:
        dropin = _perform_cutover_switch(
            args,
            config_path=config_path,
            env_path=env_path,
            database_url=database_url,
            token_file=token_file,
        )
    except Exception as exc:
        if dropin is None and isinstance(exc, CutoverSwitchError):
            dropin = exc.dropin
        _rollback_cutover_switch(
            args,
            config_path=config_path,
            env_path=env_path,
            config_backup=config_backup,
            env_backup=env_backup,
            dropin=dropin,
        )
        raise
    return _cutover_success_result(database_url, config_backup, env_path, env_backup)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--env-file", default=str(DEFAULT_ENV))
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument(
        "--control-url",
        default=os.environ.get("ENOCH_CONTROL_PLANE_URL", DEFAULT_CONTROL_URL),
    )
    parser.add_argument(
        "--token-file",
        default=os.environ.get(
            "ENOCH_CONTROL_PLANE_TOKEN_FILE", "/root/enoch-control-plane-token.txt"
        ),
    )
    parser.add_argument("--database-url", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-systemd",
        action="store_true",
        help="skip systemd changes; intended only for tests",
    )
    args = parser.parse_args()
    try:
        result = cutover(args)
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
