import sys
from pathlib import Path
import json
import unittest
from unittest.mock import patch

APP_PATH = Path(__file__).parents[1] / "ha_ai_maintainer" / "app"
sys.path.insert(0, str(APP_PATH))

from collector import (
    CollectorOptions,
    HomeAssistantAPIError,
    HomeAssistantClient,
    collect_snapshot,
    summarize_error_log,
    summarize_states,
    summarize_system_log,
)


class FakeClient:
    def get_states(self):
        return [
            {"entity_id": "sensor.ok", "state": "23", "attributes": {}},
            {
                "entity_id": "sensor.bad",
                "state": "unavailable",
                "attributes": {"friendly_name": "Bad sensor"},
            },
            {"entity_id": "switch.unknown", "state": "unknown", "attributes": {}},
        ]

    def get_system_log(self):
        return [
            {
                "level": "WARNING",
                "name": "example.warning",
                "message": ["token=top-secret"],
                "exception": "",
                "count": 1,
            },
            {
                "level": "ERROR",
                "name": "example.error",
                "message": ["failed at 192.168.1.4"],
                "exception": "",
                "count": 2,
            },
        ]


class FailingLogClient(FakeClient):
    def get_system_log(self):
        raise HomeAssistantAPIError("WebSocket unavailable")

    def get_error_log(self):
        raise HomeAssistantAPIError("HTTP Error 404")


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.responses = [
            {"type": "auth_required", "ha_version": "2026.7.0"},
            {"type": "auth_ok", "ha_version": "2026.7.0"},
            {
                "id": 1,
                "type": "result",
                "success": True,
                "result": [
                    {
                        "level": "ERROR",
                        "name": "example",
                        "message": ["failure"],
                        "exception": "",
                        "count": 1,
                    }
                ],
            },
        ]

    def recv(self):
        return json.dumps(self.responses.pop(0))

    def send(self, message):
        self.sent.append(json.loads(message))

    def close(self):
        self.closed = True


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class CollectorTests(unittest.TestCase):
    def test_state_summary(self) -> None:
        summary = summarize_states(FakeClient().get_states(), 10)
        self.assertEqual(3, summary["total"])
        self.assertEqual(1, summary["unavailable"])
        self.assertEqual(1, summary["unknown"])
        self.assertEqual(2, summary["problem_entities_total"])
        self.assertEqual(2, len(summary["problem_entities"]))
        self.assertEqual(
            [
                {"domain": "sensor", "count": 1},
                {"domain": "switch", "count": 1},
            ],
            summary["problem_domains"],
        )

    def test_error_log_summary_and_redaction(self) -> None:
        summary = summarize_error_log(
            "INFO ready\nWARNING token=top-secret\nERROR failed at 192.168.1.4",
            100,
            True,
        )
        self.assertEqual(1, summary["warnings"])
        self.assertEqual(1, summary["errors"])
        self.assertEqual(2, summary["unique_entries"])
        self.assertEqual(2, summary["total_occurrences"])
        messages = " ".join(item["message"] for item in summary["samples"])
        self.assertNotIn("top-secret", messages)
        self.assertNotIn("192.168.1.4", messages)

    def test_system_log_summary_and_redaction(self) -> None:
        summary = summarize_system_log(FakeClient().get_system_log(), 100, True)
        self.assertEqual(1, summary["warnings"])
        self.assertEqual(2, summary["errors"])
        self.assertEqual(2, summary["unique_entries"])
        self.assertEqual(3, summary["total_occurrences"])
        self.assertEqual("system_log_websocket", summary["source"])
        self.assertEqual(2, summary["samples"][0]["occurrences"])
        self.assertEqual("example.error", summary["samples"][0]["logger"])
        self.assertEqual(
            {
                "logger": "example.error",
                "occurrences": 2,
                "unique_entries": 1,
            },
            summary["top_loggers"][0],
        )
        messages = " ".join(item["message"] for item in summary["samples"])
        self.assertNotIn("top-secret", messages)
        self.assertNotIn("192.168.1.4", messages)

    def test_websocket_system_log_protocol(self) -> None:
        socket = FakeWebSocket()
        client = HomeAssistantClient(
            token="test-token",
            websocket_factory=lambda *_args, **_kwargs: socket,
        )
        entries = client.get_system_log()
        self.assertEqual("example", entries[0]["name"])
        self.assertEqual(
            {"type": "auth", "access_token": "test-token"}, socket.sent[0]
        )
        self.assertEqual({"id": 1, "type": "system_log/list"}, socket.sent[1])
        self.assertTrue(socket.closed)

    def test_ai_task_uses_response_returning_service_action(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return FakeHTTPResponse(
                {"service_response": {"data": "diagnosis"}}
            )

        client = HomeAssistantClient(
            token="test-token",
            api_base="http://example.invalid/api",
            timeout=7,
            ai_timeout=19,
        )
        with patch("collector.urlopen", fake_urlopen):
            result = client.generate_ai_task(
                "ai_task.openai_ai_task", "test", "instructions"
            )

        self.assertEqual(
            "http://example.invalid/api/services/ai_task/generate_data?return_response",
            captured["url"],
        )
        self.assertEqual("POST", captured["method"])
        self.assertEqual("ai_task.openai_ai_task", captured["payload"]["entity_id"])
        self.assertEqual(19, captured["timeout"])
        self.assertEqual("diagnosis", result["service_response"]["data"])

    def test_config_check_uses_home_assistant_validation_endpoint(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return FakeHTTPResponse({"result": "valid", "errors": None})

        client = HomeAssistantClient(
            token="test-token",
            api_base="http://example.invalid/api",
            timeout=7,
        )
        with patch("collector.urlopen", fake_urlopen):
            result = client.check_config()

        self.assertEqual(
            "http://example.invalid/api/config/core/check_config",
            captured["url"],
        )
        self.assertEqual("POST", captured["method"])
        self.assertEqual({}, captured["payload"])
        self.assertEqual(7, captured["timeout"])
        self.assertEqual("valid", result["result"])

    def test_collect_snapshot_is_read_only_summary(self) -> None:
        snapshot = collect_snapshot(FakeClient(), CollectorOptions())
        self.assertEqual("local_read_only", snapshot["mode"])
        self.assertIn("states", snapshot)
        self.assertTrue(snapshot["log"]["available"])

    def test_collect_snapshot_keeps_states_when_logs_are_unavailable(self) -> None:
        snapshot = collect_snapshot(FailingLogClient(), CollectorOptions())
        self.assertEqual(3, snapshot["states"]["total"])
        self.assertFalse(snapshot["log"]["available"])
        self.assertEqual(0, snapshot["log"]["unique_entries"])
        self.assertEqual(0, snapshot["log"]["total_occurrences"])
        self.assertIn("404", snapshot["log"]["error"])


if __name__ == "__main__":
    unittest.main()
