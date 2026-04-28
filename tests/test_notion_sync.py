from __future__ import annotations

import argparse
import json
import unittest

from omx_wake_gate.control_plane.notion_sync import (
    HttpResponse,
    apply_execution_updates,
    normalize_notion_page,
    notion_update_properties,
    query_notion_database,
    run_sync,
)


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict | None]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], payload: dict | None) -> HttpResponse:
        self.calls.append((method, url, headers, payload))
        if url.endswith("/databases/db"):
            return HttpResponse(status=200, body={"object": "database", "data_sources": [{"id": "ds-1", "name": "Ideas"}]})
        if url.endswith("/data_sources/ds-1/query"):
            return HttpResponse(status=200, body={
                "has_more": False,
                "results": [{
                    "id": "page-1",
                    "url": "https://notion.so/page-1",
                    "properties": {
                        "Idea": {"type": "title", "title": [{"plain_text": "Idea One"}]},
                        "Status": {"type": "select", "select": {"name": "exploring"}},
                        "Priority": {"type": "select", "select": {"name": "High"}},
                    },
                }],
            })
        if url.endswith("/control/intake/notion-ideas"):
            assert payload is not None
            return HttpResponse(status=200, body={"ok": True, "dry_run": payload["dry_run"], "candidates": payload["notion_rows"], "created": 0})
        if url.endswith("/control/projections/notion/execution-updates"):
            return HttpResponse(status=200, body={"ok": True, "rows": [{"page_id": "page-1", "project_id": "p1", "properties": {"Execution State": "queued", "Current Run ID": "", "Next Action": "controller_review", "Blocked Reason": "", "Last Execution Update": "2026-04-28T00:00:00Z", "Execution Summary": ""}}]})
        if "/pages/page-1" in url:
            return HttpResponse(status=200, body={"object": "page", "id": "page-1"})
        raise AssertionError(f"unexpected request {method} {url}")


class NotionSyncTests(unittest.TestCase):
    def test_normalizes_notion_page_properties(self) -> None:
        row = normalize_notion_page({
            "id": "page-1",
            "url": "https://notion.so/page-1",
            "properties": {
                "Idea": {"type": "title", "title": [{"plain_text": "Test Idea"}]},
                "Status": {"type": "select", "select": {"name": "testing"}},
                "Last Updated": {"type": "date", "date": {"start": "2026-04-28"}},
            },
        })
        self.assertEqual(row["property_idea"], "Test Idea")
        self.assertEqual(row["property_status"], "testing")
        self.assertEqual(row["property_last_updated"], "2026-04-28")

    def test_queries_database_and_paginates_shape(self) -> None:
        transport = FakeTransport()
        rows = query_notion_database("db", "secret", transport=transport)
        self.assertEqual(rows[0]["property_idea"], "Idea One")
        self.assertEqual([call[0] for call in transport.calls], ["GET", "POST"])

    def test_update_payload_uses_safe_notion_property_shapes(self) -> None:
        payload = notion_update_properties({"properties": {"Execution State": "queued", "Current Run ID": "run-1", "Next Action": "x", "Blocked Reason": "", "Last Execution Update": "2026-04-28T00:00:00Z", "Execution Summary": "summary"}})
        self.assertEqual(payload["Execution State"], {"select": {"name": "queued"}})
        self.assertEqual(payload["Current Run ID"]["rich_text"][0]["text"]["content"], "run-1")
        self.assertEqual(payload["Last Execution Update"], {"date": {"start": "2026-04-28T00:00:00Z"}})

    def test_apply_execution_updates_requires_explicit_page_id(self) -> None:
        transport = FakeTransport()
        result = apply_execution_updates([{"project_id": "p1", "properties": {}}, {"page_id": "page-1", "properties": {"Execution State": "queued"}}], "secret", transport=transport)
        self.assertFalse(result[0]["ok"])
        self.assertTrue(result[1]["ok"])
        self.assertEqual([call[0] for call in transport.calls], ["PATCH"])

    def test_runner_defaults_to_dry_run_without_writes(self) -> None:
        transport = FakeTransport()
        args = argparse.Namespace(
            control_url="http://control",
            control_token="control-secret",
            notion_token="notion-secret",
            notion_database_id="db",
            notion_data_source_id="",
            rows_json="",
            idempotency_key="test-sync",
            include_status=["exploring", "testing"],
            apply_intake=False,
            apply_notion_updates=False,
            max_updates=None,
        )
        result = run_sync(args, transport=transport)
        self.assertTrue(result["ok"])
        self.assertFalse(result["mode"]["apply_intake"])
        self.assertEqual(result["notion_rows_read"], 1)
        methods = [call[0] for call in transport.calls]
        self.assertEqual(methods, ["GET", "POST", "POST", "GET"])

    def test_runner_apply_mode_patches_projected_updates(self) -> None:
        transport = FakeTransport()
        args = argparse.Namespace(
            control_url="http://control",
            control_token="control-secret",
            notion_token="notion-secret",
            notion_database_id="db",
            notion_data_source_id="",
            rows_json="",
            idempotency_key="test-sync-apply",
            include_status=["exploring", "testing"],
            apply_intake=True,
            apply_notion_updates=True,
            max_updates=1,
        )
        result = run_sync(args, transport=transport)
        self.assertTrue(result["mode"]["apply_intake"])
        self.assertEqual(result["notion_updates_applied"][0]["page_id"], "page-1")
        methods = [call[0] for call in transport.calls]
        self.assertEqual(methods, ["GET", "POST", "POST", "GET", "PATCH"])


if __name__ == "__main__":
    unittest.main()
