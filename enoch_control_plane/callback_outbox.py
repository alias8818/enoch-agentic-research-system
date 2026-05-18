from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any
from urllib import error, request

from .url_safety import validate_http_url


OUTBOX_DIRNAME = "callback_outbox"
DELIVERED_DIRNAME = "callback_delivered"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def outbox_dir(state_dir: str | Path) -> Path:
    path = Path(state_dir).expanduser() / OUTBOX_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def delivered_dir(state_dir: str | Path) -> Path:
    path = Path(state_dir).expanduser() / DELIVERED_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _legacy_safe_run_id(run_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-+" else "_" for ch in str(run_id))
    return safe or "unknown-run"


def _safe_run_id(run_id: str) -> str:
    raw = str(run_id)
    safe = _legacy_safe_run_id(raw)
    if raw and safe == raw and len(safe) <= 100:
        return safe
    digest = hashlib.blake2s(raw.encode("utf-8"), digest_size=4).hexdigest()
    return f"{safe[:80]}-{digest}"


def pending_path(state_dir: str | Path, run_id: str) -> Path:
    return outbox_dir(state_dir) / f"{_safe_run_id(run_id)}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            tmp = Path(fh.name)
        tmp.replace(path)
    finally:
        if tmp is not None:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def write_pending(state_dir: str | Path, payload: dict[str, Any]) -> Path:
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        raise ValueError("callback payload is missing run_id")
    record = dict(payload)
    record.setdefault("outbox_created_at", utc_now())
    record.setdefault("attempt_count", 0)
    record.setdefault("last_attempt_at", "")
    record.setdefault("last_error", "")
    path = pending_path(state_dir, run_id)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            record["outbox_created_at"] = existing.get("outbox_created_at") or record["outbox_created_at"]
            record["attempt_count"] = int(existing.get("attempt_count") or 0)
            record["last_attempt_at"] = existing.get("last_attempt_at") or ""
            record["last_error"] = existing.get("last_error") or ""
        except Exception as exc:
            record["last_error"] = f"existing pending metadata unreadable: {type(exc).__name__}: {exc}"
    _atomic_write_json(path, record)
    return path


def _mark_local_worker_state_delivered(state_dir: str | Path, payload: dict[str, Any]) -> str:
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        return ""
    run_dir = Path(state_dir).expanduser() / "runs"
    path = run_dir / f"{_safe_run_id(run_id)}.json"
    legacy_path = run_dir / f"{_legacy_safe_run_id(run_id)}.json"
    if not path.exists() and legacy_path != path and legacy_path.exists():
        path = legacy_path
    if not path.exists():
        return ""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        record["gate_state"] = payload.get("gate_state") or record.get("gate_state")
        record["last_idempotency_key"] = payload.get("idempotency_key") or record.get("last_idempotency_key")
        record["updated_at"] = utc_now()
        _atomic_write_json(path, record)
        return ""
    except Exception as exc:
        return f"local worker state update failed: {type(exc).__name__}: {exc}"


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    status_code: int | None = None
    detail: str = ""
    path: str = ""


def deliver_payload(payload: dict[str, Any], *, url: str, token: str, timeout: float) -> DeliveryResult:
    try:
        safe_url = validate_http_url(url, field_name="callback url")
    except ValueError as exc:
        return DeliveryResult(ok=False, detail=str(exc))
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        safe_url,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - operator-configured callback URL
            body = resp.read(4096).decode("utf-8", errors="replace")
            return DeliveryResult(ok=200 <= resp.status < 300, status_code=resp.status, detail=body)
    except error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        return DeliveryResult(ok=False, status_code=exc.code, detail=body)
    except Exception as exc:
        return DeliveryResult(ok=False, detail=f"{type(exc).__name__}: {exc}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def deliver_pending_file(path: str | Path, *, state_dir: str | Path, url: str, token: str, timeout: float) -> DeliveryResult:
    try:
        pending = Path(path).expanduser()
        pending_resolved = pending.resolve(strict=False)
        outbox_resolved = outbox_dir(state_dir).resolve(strict=False)
    except Exception as exc:
        return DeliveryResult(ok=False, detail=f"invalid callback outbox path: {type(exc).__name__}: {exc}", path=str(path))
    if not _is_relative_to(pending_resolved, outbox_resolved):
        return DeliveryResult(ok=False, detail="pending callback path is outside callback outbox", path=str(pending))
    try:
        payload = json.loads(pending.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return DeliveryResult(
            ok=False,
            detail=f"pending callback payload unreadable: {type(exc).__name__}: {exc}",
            path=str(pending),
        )
    payload["attempt_count"] = int(payload.get("attempt_count") or 0) + 1
    payload["last_attempt_at"] = utc_now()
    result = deliver_payload(payload, url=url, token=token, timeout=timeout)
    if result.ok:
        payload["delivered_at"] = utc_now()
        payload["last_error"] = ""
        dest = delivered_dir(state_dir) / pending.name
        _atomic_write_json(dest, payload)
        try:
            pending.unlink()
        except FileNotFoundError:
            pass
        local_state_error = _mark_local_worker_state_delivered(state_dir, payload)
        if local_state_error:
            payload["local_worker_state_error"] = local_state_error
            _atomic_write_json(dest, payload)
            detail = f"{result.detail}\n{local_state_error}" if result.detail else local_state_error
            return DeliveryResult(ok=True, status_code=result.status_code, detail=detail, path=str(dest))
        return DeliveryResult(ok=True, status_code=result.status_code, detail=result.detail, path=str(dest))
    payload["last_error"] = result.detail
    _atomic_write_json(pending, payload)
    return DeliveryResult(ok=False, status_code=result.status_code, detail=result.detail, path=str(pending))


def replay_pending(*, state_dir: str | Path, url: str, token: str, timeout: float = 30.0, limit: int = 20) -> list[DeliveryResult]:
    if not url or not token:
        return []
    pending = sorted(outbox_dir(state_dir).glob("*.json"), key=lambda p: p.stat().st_mtime)[: max(0, limit)]
    results: list[DeliveryResult] = []
    for path in pending:
        try:
            results.append(deliver_pending_file(path, state_dir=state_dir, url=url, token=token, timeout=timeout))
        except Exception as exc:
            results.append(DeliveryResult(ok=False, detail=f"{type(exc).__name__}: {exc}", path=str(path)))
    return results


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Manage Enoch callback outbox records")
    sub = parser.add_subparsers(dest="cmd", required=True)
    write = sub.add_parser("write")
    write.add_argument("--state-dir", required=True)
    write.add_argument("--payload-file", required=True)
    deliver = sub.add_parser("deliver")
    deliver.add_argument("--state-dir", required=True)
    deliver.add_argument("--run-id", required=True)
    deliver.add_argument("--url", required=True)
    deliver_token = deliver.add_mutually_exclusive_group(required=True)
    deliver_token.add_argument("--token")
    deliver_token.add_argument("--token-stdin", action="store_true", help="read bearer token from stdin instead of argv")
    deliver.add_argument("--timeout", type=float, default=30.0)
    replay = sub.add_parser("replay")
    replay.add_argument("--state-dir", required=True)
    replay.add_argument("--url", required=True)
    replay_token = replay.add_mutually_exclusive_group(required=True)
    replay_token.add_argument("--token")
    replay_token.add_argument("--token-stdin", action="store_true", help="read bearer token from stdin instead of argv")
    replay.add_argument("--timeout", type=float, default=30.0)
    replay.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    if args.cmd == "write":
        payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
        path = write_pending(args.state_dir, payload)
        print(json.dumps({"ok": True, "path": str(path)}, sort_keys=True))
        return 0
    if args.cmd == "deliver":
        token = sys.stdin.read().rstrip("\r\n") if args.token_stdin else args.token
        result = deliver_pending_file(pending_path(args.state_dir, args.run_id), state_dir=args.state_dir, url=args.url, token=token, timeout=args.timeout)
        print(json.dumps(result.__dict__, sort_keys=True))
        return 0 if result.ok else 1
    if args.cmd == "replay":
        token = sys.stdin.read().rstrip("\r\n") if args.token_stdin else args.token
        results = replay_pending(state_dir=args.state_dir, url=args.url, token=token, timeout=args.timeout, limit=args.limit)
        print(json.dumps({"ok": all(r.ok for r in results), "results": [r.__dict__ for r in results]}, sort_keys=True))
        return 0 if all(r.ok for r in results) else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
