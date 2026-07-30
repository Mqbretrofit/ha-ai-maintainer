import sys
from pathlib import Path
import unittest

APP_PATH = Path(__file__).parents[1] / "ha_ai_maintainer" / "app"
sys.path.insert(0, str(APP_PATH))

from collector import (
    CollectorOptions,
    collect_snapshot,
    summarize_error_log,
    summarize_states,
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

    def get_error_log(self):
        return "INFO ready\nWARNING token=top-secret\nERROR failed at 192.168.1.4"


class CollectorTests(unittest.TestCase):
    def test_state_summary(self) -> None:
        summary = summarize_states(FakeClient().get_states(), 10)
        self.assertEqual(3, summary["total"])
        self.assertEqual(1, summary["unavailable"])
        self.assertEqual(1, summary["unknown"])
        self.assertEqual(2, len(summary["problem_entities"]))

    def test_error_log_summary_and_redaction(self) -> None:
        summary = summarize_error_log(FakeClient().get_error_log(), 100, True)
        self.assertEqual(1, summary["warnings"])
        self.assertEqual(1, summary["errors"])
        messages = " ".join(item["message"] for item in summary["samples"])
        self.assertNotIn("top-secret", messages)
        self.assertNotIn("192.168.1.4", messages)

    def test_collect_snapshot_is_read_only_summary(self) -> None:
        snapshot = collect_snapshot(FakeClient(), CollectorOptions())
        self.assertEqual("local_read_only", snapshot["mode"])
        self.assertIn("states", snapshot)
        self.assertIn("log", snapshot)


if __name__ == "__main__":
    unittest.main()
