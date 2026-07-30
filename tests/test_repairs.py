import json
from pathlib import Path
import sys
import unittest

APP_PATH = Path(__file__).parents[1] / "ha_ai_maintainer" / "app"
sys.path.insert(0, str(APP_PATH))

from repairs import (
    RepairDispatchError,
    dispatch_repair,
    find_repair_candidates,
)


SNAPSHOT = {
    "log": {
        "samples": [
            {
                "logger": "homeassistant.components.recorder.db_schema",
                "message": (
                    "State attributes for sensor.robot_funyiro_anthbot_map "
                    "exceed maximum size of 16384 bytes."
                ),
            }
        ]
    }
}


class FakeResponse:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class RepairTests(unittest.TestCase):
    def test_detects_allowlisted_anthbot_map_warning(self) -> None:
        candidates = find_repair_candidates(SNAPSHOT)
        self.assertEqual(1, len(candidates))
        self.assertEqual("anthbot_map_attributes_too_large", candidates[0]["id"])
        self.assertEqual("Mqbretrofit/ha-anthbot-map", candidates[0]["repository"])

    def test_does_not_route_unrelated_large_attribute_warning(self) -> None:
        snapshot = {
            "log": {
                "samples": [
                    {
                        "logger": "homeassistant.components.recorder.db_schema",
                        "message": (
                            "State attributes for sensor.phone_notifications "
                            "exceed maximum size of 16384 bytes."
                        ),
                    }
                ]
            }
        }
        self.assertEqual([], find_repair_candidates(snapshot))

    def test_dispatch_sends_only_allowlisted_identifier(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        result = dispatch_repair(
            "github_pat_test",
            "anthbot_map_attributes_too_large",
            opener=opener,
        )
        payload = json.loads(captured["request"].data)
        self.assertEqual(
            {
                "ref": "main",
                "inputs": {"repair_id": "map_attributes_too_large"},
            },
            payload,
        )
        self.assertNotIn("sensor.robot", json.dumps(payload))
        self.assertEqual("dispatched", result["status"])
        self.assertEqual(20, captured["timeout"])

    def test_rejects_unknown_target_and_missing_token(self) -> None:
        with self.assertRaisesRegex(RepairDispatchError, "nincs engedélyezve"):
            dispatch_repair("github_pat_test", "unknown")
        with self.assertRaisesRegex(RepairDispatchError, "Nincs beállítva"):
            dispatch_repair("", "anthbot_map_attributes_too_large")


if __name__ == "__main__":
    unittest.main()
