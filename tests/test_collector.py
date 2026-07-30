import sys
from pathlib import Path
import json
import unittest

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
