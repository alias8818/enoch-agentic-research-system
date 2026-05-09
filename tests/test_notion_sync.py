from __future__ import annotations

import argparse
import json
import unittest
from urllib import error

from enoch_control_plane.control_plane.notion_sync import (
    HttpResponse,
    NotionSyncError,
    apply_execution_updates,
    normalize_notion_page,
    notion_update_properties,
    query_notion_database,
    run_sync,
    main,
    _json_request,
)


def json_dumps(value: object) -> str:
    return json.dumps(value)


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
        if url.endswith("/pages/page-1") and method == "GET":
            return HttpResponse(status=200, body={"object": "page", "id": "page-1", "properties": {"Execution State": {}, "Current Run ID": {}, "Next Action": {}, "Blocked Reason": {}, "Last Execution Update": {}, "Execution Summary": {}, "Enoch Project ID": {}}})
        if url.endswith("/pages/page-1") and method == "PATCH":
            assert payload is not None
            assert "Enoch Queue Status" not in payload["properties"]
            return HttpResponse(status=200, body={"object": "page", "id": "page-1"})
        raise AssertionError(f"unexpected request {method} {url}")


class NotionSyncTests(unittest.TestCase):

    def test_cli_main_is_disabled_unless_legacy_sync_is_explicitly_enabled(self) -> None:
        from unittest import mock

        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(main([]), 0)

    def test_json_request_retries_transient_url_errors(self) -> None:
        calls = {"count": 0}

        def opener(req, timeout):  # noqa: ANN001
            calls["count"] += 1
            if calls["count"] == 1:
                raise error.URLError("timed out")

            class Response:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def read(self):
                    return b'{"ok": true}'

            return Response()

        from unittest import mock

        with mock.patch("enoch_control_plane.control_plane.notion_sync.request.urlopen", opener), mock.patch(
            "enoch_control_plane.control_plane.notion_sync.time.sleep", lambda _seconds: None
        ), mock.patch.dict("os.environ", {"ENOCH_NOTION_HTTP_TIMEOUT_SEC": "1", "ENOCH_NOTION_HTTP_ATTEMPTS": "2"}):
            response = _json_request("GET", "https://example.test", {}, None)

        self.assertEqual(response.body, {"ok": True})
        self.assertEqual(calls["count"], 2)

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
        payload = notion_update_properties({"properties": {"Execution State": "queued", "Current Run ID": "run-1", "Next Action": "x", "Blocked Reason": "", "Last Execution Update": "2026-04-28T00:00:00Z", "Execution Summary": "summary", "Enoch Project ID": "idea-1", "Enoch Queue Status": "queued", "Enoch Manual Review Required": "__YES__", "Enoch Dispatch Priority": 7, "Enoch Paper Updated At": "2026-04-28T01:00:00Z"}})
        self.assertEqual(payload["Execution State"], {"select": {"name": "queued"}})
        self.assertEqual(payload["Current Run ID"]["rich_text"][0]["text"]["content"], "run-1")
        self.assertEqual(payload["Last Execution Update"], {"date": {"start": "2026-04-28T00:00:00Z"}})
        self.assertEqual(payload["Enoch Project ID"]["rich_text"][0]["text"]["content"], "idea-1")
        self.assertEqual(payload["Enoch Manual Review Required"], {"checkbox": True})
        self.assertEqual(payload["Enoch Dispatch Priority"], {"number": 7})
        self.assertEqual(payload["Enoch Paper Updated At"], {"date": {"start": "2026-04-28T01:00:00Z"}})

    def test_apply_execution_updates_requires_explicit_page_id(self) -> None:
        transport = FakeTransport()
        result = apply_execution_updates([{"project_id": "p1", "properties": {}}, {"page_id": "page-1", "properties": {"Execution State": "queued"}}], "secret", transport=transport)
        self.assertFalse(result[0]["ok"])
        self.assertTrue(result[1]["ok"])
        self.assertEqual([call[0] for call in transport.calls], ["GET", "PATCH"])
        patched = transport.calls[-1][3]["properties"]
        self.assertIn("Execution State", patched)
        self.assertIn("Current Run ID", patched)
        self.assertNotIn("Enoch Queue Status", patched)

    def test_apply_execution_updates_skips_when_page_has_no_supported_properties(self) -> None:
        def transport(method: str, url: str, headers: dict, payload: dict | None) -> HttpResponse:
            if method == "GET" and url.endswith("/pages/page-empty"):
                return HttpResponse(status=200, body={"properties": {"Idea": {}}})
            raise AssertionError(f"unexpected request {method} {url}")
        result = apply_execution_updates([{"page_id": "page-empty", "project_id": "p1", "properties": {"Execution State": "queued"}}], "secret", transport=transport)
        self.assertFalse(result[0]["ok"])
        self.assertEqual(result[0]["reason"], "no supported properties")
        self.assertIn("Execution State", result[0]["skipped_properties"])

    def test_apply_execution_updates_skips_when_page_property_probe_fails(self) -> None:
        def transport(method: str, url: str, headers: dict, payload: dict | None) -> HttpResponse:
            if method == "GET" and url.endswith("/pages/page-fail"):
                raise NotionSyncError("probe failed")
            raise AssertionError(f"unexpected request {method} {url}")
        result = apply_execution_updates([{"page_id": "page-fail", "project_id": "p1", "properties": {"Execution State": "queued"}}], "secret", transport=transport)
        self.assertFalse(result[0]["ok"])
        self.assertEqual(result[0]["reason"], "page property probe failed")

    def test_runner_allows_data_source_only_live_read(self) -> None:
        transport = FakeTransport()
        args = argparse.Namespace(
            control_url="http://control",
            control_token="control-secret",
            notion_token="notion-secret",
            notion_database_id="",
            notion_data_source_id="ds-1",
            rows_json="",
            idempotency_key="test-sync-data-source-only",
            include_status=["exploring", "testing"],
            apply_intake=False,
            apply_notion_updates=False,
            override_existing_dispatch_metadata=False,
            max_updates=None,
        )
        result = run_sync(args, transport=transport)
        self.assertTrue(result["ok"])
        self.assertEqual(result["notion_rows_read"], 1)
        self.assertEqual([call[0] for call in transport.calls], ["POST", "POST", "GET"])
        self.assertIn("/data_sources/ds-1/query", transport.calls[0][1])

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
            override_existing_dispatch_metadata=False,
            max_updates=None,
        )
        result = run_sync(args, transport=transport)
        self.assertTrue(result["ok"])
        self.assertFalse(result["mode"]["apply_intake"])
        intake_payload = next(call[3] for call in transport.calls if call[1].endswith("/control/intake/notion-ideas"))
        self.assertEqual(intake_payload["default_machine_target"], "worker.example")
        self.assertEqual(intake_payload["default_model"], "gpt-5.5")
        self.assertEqual(intake_payload["default_sandbox"], "danger-full-access")
        self.assertFalse(intake_payload["override_existing_dispatch_metadata"])
        self.assertEqual(result["notion_rows_read"], 1)
        methods = [call[0] for call in transport.calls]
        self.assertEqual(methods, ["GET", "POST", "POST", "GET"])

    def test_runner_forwards_explicit_default_dispatch_metadata(self) -> None:
        transport = FakeTransport()
        rows = [{
            "id": "page-new",
            "url": "https://notion.so/page-new",
            "properties": {
                "Idea": {"type": "title", "title": [{"plain_text": "New Idea"}]},
                "Status": {"type": "select", "select": {"name": "exploring"}},
            },
        }]
        args = argparse.Namespace(
            control_url="http://control",
            control_token="control-secret",
            notion_token="",
            notion_database_id="",
            notion_data_source_id="",
            rows_json=json_dumps(rows),
            idempotency_key="test-sync-explicit-defaults",
            include_status=["exploring"],
            default_machine_target="192.168.1.77",
            default_model="gpt-5.5",
            default_sandbox="danger-full-access",
            apply_intake=True,
            apply_notion_updates=False,
            override_existing_dispatch_metadata=False,
            max_updates=None,
        )

        result = run_sync(args, transport=transport)

        self.assertTrue(result["ok"])
        intake_payload = next(call[3] for call in transport.calls if call[1].endswith("/control/intake/notion-ideas"))
        self.assertEqual(intake_payload["default_machine_target"], "192.168.1.77")
        self.assertEqual(intake_payload["default_model"], "gpt-5.5")
        self.assertEqual(intake_payload["default_sandbox"], "danger-full-access")
        self.assertFalse(intake_payload["override_existing_dispatch_metadata"])

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
            override_existing_dispatch_metadata=True,
            max_updates=1,
        )
        result = run_sync(args, transport=transport)
        self.assertTrue(result["mode"]["apply_intake"])
        intake_payload = next(call[3] for call in transport.calls if call[1].endswith("/control/intake/notion-ideas"))
        self.assertTrue(intake_payload["override_existing_dispatch_metadata"])
        self.assertEqual(result["notion_updates_applied"][0]["page_id"], "page-1")
        self.assertEqual(result["notion_updates_applied_count"], 1)
        self.assertEqual(result["notion_updates_skipped_count"], 0)
        methods = [call[0] for call in transport.calls]
        self.assertEqual(methods, ["GET", "POST", "POST", "GET", "GET", "PATCH"])
        patched = transport.calls[-1][3]["properties"]
        self.assertIn("Execution State", patched)
        self.assertNotIn("Enoch Queue Status", patched)


if __name__ == "__main__":
    unittest.main()
