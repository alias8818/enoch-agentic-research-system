from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, request

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


class NotionSyncError(RuntimeError):
    pass


@dataclass
class HttpResponse:
    status: int
    body: dict[str, Any]


Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], HttpResponse]


def _json_request(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None) -> HttpResponse:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return HttpResponse(status=resp.status, body=json.loads(raw) if raw else {})
    except error.HTTPError as exc:  # pragma: no cover - exercised by integration use
        raw = exc.read().decode("utf-8")
        detail = raw or exc.reason
        raise NotionSyncError(f"{method} {url} failed with {exc.code}: {detail}") from exc


def notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def control_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def extract_plain_text(prop: dict[str, Any]) -> str:
    kind = prop.get("type")
    values = prop.get(kind) if kind else None
    if isinstance(values, list):
        return "".join(str(item.get("plain_text") or item.get("text", {}).get("content") or "") for item in values).strip()
    if isinstance(values, dict):
        return str(values.get("name") or values.get("start") or values.get("content") or "").strip()
    if isinstance(values, (str, int, float)):
        return str(values)
    return ""


def normalize_notion_page(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("properties") or {}
    row: dict[str, Any] = {
        "id": page.get("id") or "",
        "url": page.get("url") or page.get("public_url") or "",
    }
    for name, prop in props.items():
        safe = name.lower().replace(" ", "_")
        row[f"property_{safe}"] = extract_plain_text(prop) if isinstance(prop, dict) else ""
    if "property_idea" not in row:
        for candidate in ("property_name", "property_title"):
            if row.get(candidate):
                row["property_idea"] = row[candidate]
                break
    return row


def resolve_data_source_id(database_or_data_source_id: str, token: str, *, transport: Transport = _json_request) -> str:
    """Return a Notion data source ID for current Notion API versions.

    Notion split databases and data sources in API versions >= 2025-09-03.
    Operators often still have the parent database ID from old workflows, so
    retrieve the database and use its first data source when needed. If the ID
    is already a data source ID or database retrieval is unavailable, callers can
    pass it directly via --notion-data-source-id.
    """
    url = f"{NOTION_API_BASE}/databases/{database_or_data_source_id}"
    try:
        resp = transport("GET", url, notion_headers(token), None)
    except NotionSyncError:
        return database_or_data_source_id
    data_sources = resp.body.get("data_sources") or []
    if data_sources and isinstance(data_sources[0], dict) and data_sources[0].get("id"):
        return str(data_sources[0]["id"])
    return database_or_data_source_id


def query_notion_database(database_id: str, token: str, *, transport: Transport = _json_request, page_size: int = 100, data_source_id: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    source_id = data_source_id or resolve_data_source_id(database_id, token, transport=transport)
    url = f"{NOTION_API_BASE}/data_sources/{source_id}/query"
    headers = notion_headers(token)
    while True:
        payload: dict[str, Any] = {"page_size": page_size}
        if cursor:
            payload["start_cursor"] = cursor
        resp = transport("POST", url, headers, payload)
        body = resp.body
        rows.extend(normalize_notion_page(page) for page in body.get("results", []) if isinstance(page, dict))
        if not body.get("has_more"):
            break
        cursor = body.get("next_cursor")
        if not cursor:
            break
    return rows


def _rich_text(value: str, *, limit: int = 1900) -> dict[str, Any]:
    text = (value or "")[:limit]
    return {"rich_text": [{"text": {"content": text}}] if text else []}


def _select(value: str) -> dict[str, Any]:
    return {"select": {"name": value} if value else None}


def _date(value: str) -> dict[str, Any]:
    return {"date": {"start": value} if value else None}


def _number(value: Any) -> dict[str, Any]:
    try:
        return {"number": int(value)}
    except (TypeError, ValueError):
        return {"number": None}


def _checkbox(value: Any) -> dict[str, Any]:
    if value in {True, 1, "1", "true", "True", "TRUE", "__YES__"}:
        return {"checkbox": True}
    return {"checkbox": False}


def notion_update_properties(row: dict[str, Any]) -> dict[str, Any]:
    props = row.get("properties") or {}
    payload = {
        "Execution State": _select(str(props.get("Execution State") or "")),
        "Current Run ID": _rich_text(str(props.get("Current Run ID") or "")),
        "Next Action": _rich_text(str(props.get("Next Action") or "")),
        "Blocked Reason": _rich_text(str(props.get("Blocked Reason") or "")),
        "Last Execution Update": _date(str(props.get("Last Execution Update") or "")),
        "Execution Summary": _rich_text(str(props.get("Execution Summary") or "")),
    }
    text_fields = [
        "OMX Project ID", "OMX Queue Status", "OMX Last Run State", "OMX Last Event Type",
        "OMX Next Action Hint", "OMX Project Dir", "OMX Current Session ID",
        "OMX Last Result Summary", "OMX Last Error", "OMX Paper ID", "OMX Paper Status",
        "OMX Paper Type", "OMX Paper Markdown Path", "OMX Paper Updated At ISO",
    ]
    for field in text_fields:
        payload[field] = _rich_text(str(props.get(field) or ""))
    for field in ("OMX Dispatch Priority", "OMX Selection Rank"):
        payload[field] = _number(props.get(field))
    payload["OMX Manual Review Required"] = _checkbox(props.get("OMX Manual Review Required"))
    payload["OMX Paper Updated At"] = _date(str(props.get("OMX Paper Updated At") or ""))
    return payload


def control_post(base_url: str, token: str, path: str, payload: dict[str, Any], *, transport: Transport = _json_request) -> dict[str, Any]:
    resp = transport("POST", base_url.rstrip("/") + path, control_headers(token), payload)
    return resp.body


def control_get(base_url: str, token: str, path: str, *, transport: Transport = _json_request) -> dict[str, Any]:
    resp = transport("GET", base_url.rstrip("/") + path, control_headers(token), None)
    return resp.body


def _existing_page_property_names(page_id: str, headers: dict[str, str], *, transport: Transport) -> set[str] | None:
    try:
        resp = transport("GET", f"{NOTION_API_BASE}/pages/{page_id}", headers, None)
    except NotionSyncError:
        return None
    props = resp.body.get("properties") if isinstance(resp.body, dict) else None
    return set(props.keys()) if isinstance(props, dict) else set()


def apply_execution_updates(
    rows: list[dict[str, Any]],
    token: str,
    *,
    transport: Transport = _json_request,
    max_updates: int | None = None,
    filter_to_existing_properties: bool = True,
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    headers = notion_headers(token)
    for row in rows[:max_updates or len(rows)]:
        page_id = str(row.get("page_id") or "").strip()
        if not page_id:
            # We intentionally do not parse page IDs from URLs here; the Notion
            # adapter should provide explicit IDs to avoid updating the wrong page.
            applied.append({"ok": False, "reason": "missing page_id", "project_id": row.get("project_id")})
            continue
        properties = notion_update_properties(row)
        skipped_properties: list[str] = []
        if filter_to_existing_properties:
            existing = _existing_page_property_names(page_id, headers, transport=transport)
            if existing is None:
                applied.append({"ok": False, "reason": "page property probe failed", "page_id": page_id, "project_id": row.get("project_id")})
                continue
            skipped_properties = sorted(name for name in properties if name not in existing)
            properties = {name: value for name, value in properties.items() if name in existing}
        if not properties:
            applied.append({"ok": False, "reason": "no supported properties", "page_id": page_id, "project_id": row.get("project_id"), "skipped_properties": skipped_properties})
            continue
        payload = {"properties": properties}
        resp = transport("PATCH", f"{NOTION_API_BASE}/pages/{page_id}", headers, payload)
        applied.append({"ok": True, "page_id": page_id, "status": resp.status, "properties_patched": sorted(properties), "skipped_properties": skipped_properties})
    return applied


def run_sync(args: argparse.Namespace, *, transport: Transport = _json_request) -> dict[str, Any]:
    control_token = args.control_token or os.environ.get("ENOCH_CONTROL_TOKEN", "")
    notion_token = args.notion_token or os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY", "")
    if not control_token:
        raise NotionSyncError("missing control token; pass --control-token or ENOCH_CONTROL_TOKEN")
    rows: list[dict[str, Any]]
    if args.rows_json:
        rows = json.loads(args.rows_json)
    else:
        if not notion_token or not (args.notion_database_id or args.notion_data_source_id):
            raise NotionSyncError("missing Notion token and database/data-source for live read; pass --rows-json for offline dry runs")
        rows = query_notion_database(args.notion_database_id or args.notion_data_source_id, notion_token, transport=transport, data_source_id=args.notion_data_source_id)
    intake = control_post(
        args.control_url,
        control_token,
        "/control/intake/notion-ideas",
        {
            "idempotency_key": args.idempotency_key,
            "source": "notion-sync-runner",
            "notion_rows": rows,
            "dry_run": not args.apply_intake,
            "include_statuses": args.include_status,
        },
        transport=transport,
    )
    projection = control_get(args.control_url, control_token, "/control/projections/notion/execution-updates", transport=transport)
    applied: list[dict[str, Any]] = []
    if args.apply_notion_updates:
        if not notion_token:
            raise NotionSyncError("missing Notion token for apply updates")
        applied = apply_execution_updates(projection.get("rows", []), notion_token, transport=transport, max_updates=args.max_updates)
    applied_ok = sum(1 for item in applied if item.get("ok"))
    applied_skipped = sum(1 for item in applied if not item.get("ok"))
    return {
        "ok": True,
        "mode": {"apply_intake": args.apply_intake, "apply_notion_updates": args.apply_notion_updates},
        "notion_rows_read": len(rows),
        "intake": intake,
        "execution_projection_count": len(projection.get("rows", [])),
        "notion_updates_applied": applied,
        "notion_updates_applied_count": applied_ok,
        "notion_updates_skipped_count": applied_skipped,
        "notion_updates_missing_page_id_count": sum(1 for item in applied if item.get("reason") == "missing page_id"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync Notion intake/projections with the Enoch LangGraph control plane.")
    parser.add_argument("--control-url", default=os.environ.get("ENOCH_CONTROL_URL", "http://127.0.0.1:8787"))
    parser.add_argument("--control-token", default="")
    parser.add_argument("--notion-token", default="")
    parser.add_argument("--notion-database-id", default=os.environ.get("NOTION_DATABASE_ID", ""))
    parser.add_argument("--notion-data-source-id", default=os.environ.get("NOTION_DATA_SOURCE_ID", ""))
    parser.add_argument("--rows-json", default="", help="Offline JSON array of normalized Notion rows; bypasses live Notion read.")
    parser.add_argument("--idempotency-key", default="notion-sync-manual")
    parser.add_argument("--include-status", action="append", default=["exploring", "testing"])
    parser.add_argument("--apply-intake", action="store_true", help="Commit eligible Notion ideas into canonical queue. Default is dry-run.")
    parser.add_argument("--apply-notion-updates", action="store_true", help="PATCH Notion execution overlay fields. Default is read-only.")
    parser.add_argument("--max-updates", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_sync(args)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
