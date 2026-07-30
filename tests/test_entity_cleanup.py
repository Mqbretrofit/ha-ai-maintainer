from pathlib import Path
from datetime import UTC, datetime
import sys
import unittest

APP_PATH = Path(__file__).parents[1] / "ha_ai_maintainer" / "app"
sys.path.insert(0, str(APP_PATH))

from entity_cleanup import (
    EntityCleanupError,
    delete_entity_cleanup_candidates,
    find_entity_cleanup_candidates,
)


class FakeRegistryClient:
    def __init__(self):
        self.states = [
            {
                "entity_id": "sensor.orphan",
                "state": "unavailable",
                "attributes": {"friendly_name": "Old sensor"},
            },
            {
                "entity_id": "sensor.active_but_offline",
                "state": "unavailable",
                "attributes": {},
            },
            {
                "entity_id": "sensor.long_unavailable",
                "state": "unavailable",
                "last_changed": "2020-05-01T00:00:00+00:00",
                "attributes": {},
            },
            {
                "entity_id": "sensor.yaml_sensor",
                "state": "unavailable",
                "attributes": {},
            },
            {
                "entity_id": "sensor.healthy",
                "state": "12",
                "attributes": {},
            },
        ]
        self.registry = [
            {
                "entity_id": "sensor.orphan",
                "config_entry_id": "removed-entry",
                "platform": "esphome",
                "original_name": "Old sensor",
            },
            {
                "entity_id": "sensor.active_but_offline",
                "config_entry_id": "active-entry",
                "platform": "esphome",
            },
            {
                "entity_id": "sensor.long_unavailable",
                "config_entry_id": "active-entry",
                "platform": "esphome",
            },
            {
                "entity_id": "sensor.yaml_sensor",
                "config_entry_id": None,
                "platform": "template",
            },
            {
                "entity_id": "sensor.healthy",
                "config_entry_id": "removed-entry",
                "platform": "esphome",
            },
        ]
        self.config_entries = [{"entry_id": "active-entry"}]
        self.removed = []

    def get_states(self):
        return self.states

    def get_entity_registry(self):
        return self.registry

    def get_config_entries(self):
        return self.config_entries

    def remove_entity_registry_entry(self, entity_id):
        self.removed.append(entity_id)
        self.registry = [
            item for item in self.registry if item["entity_id"] != entity_id
        ]
        self.states = [
            item for item in self.states if item["entity_id"] != entity_id
        ]


class EntityCleanupTests(unittest.TestCase):
    def test_only_unavailable_entry_with_missing_config_entry_is_candidate(self):
        candidates = find_entity_cleanup_candidates(
            FakeRegistryClient(),
            now=datetime(2026, 7, 30, tzinfo=UTC),
        )

        self.assertEqual(
            ["sensor.long_unavailable", "sensor.orphan"],
            [item["entity_id"] for item in candidates],
        )
        orphan = next(
            item for item in candidates if item["entity_id"] == "sensor.orphan"
        )
        self.assertEqual("Old sensor", orphan["name"])
        self.assertEqual(
            "long_unavailable",
            next(
                item
                for item in candidates
                if item["entity_id"] == "sensor.long_unavailable"
            )["kind"],
        )

    def test_delete_revalidates_candidate_before_removal(self):
        client = FakeRegistryClient()

        result = delete_entity_cleanup_candidates(client, ["sensor.orphan"])

        self.assertEqual(["sensor.orphan"], client.removed)
        self.assertEqual(1, result["count"])

    def test_delete_refuses_entity_backed_by_active_config_entry(self):
        client = FakeRegistryClient()

        with self.assertRaisesRegex(EntityCleanupError, "nem biztonságos"):
            delete_entity_cleanup_candidates(client, ["sensor.active_but_offline"])

        self.assertEqual([], client.removed)

    def test_delete_refuses_yaml_entry_without_config_entry(self):
        client = FakeRegistryClient()

        with self.assertRaisesRegex(EntityCleanupError, "nem biztonságos"):
            delete_entity_cleanup_candidates(client, ["sensor.yaml_sensor"])

        self.assertEqual([], client.removed)

    def test_delete_refuses_more_than_limit(self):
        client = FakeRegistryClient()
        with self.assertRaisesRegex(EntityCleanupError, "legfeljebb"):
            delete_entity_cleanup_candidates(
                client,
                [f"sensor.test_{index}" for index in range(51)],
            )

    def test_delete_reports_partial_failure(self):
        client = FakeRegistryClient()

        def fail_remove(_entity_id):
            raise RuntimeError("admin permission required")

        client.remove_entity_registry_entry = fail_remove
        result = delete_entity_cleanup_candidates(client, ["sensor.orphan"])

        self.assertEqual([], result["deleted"])
        self.assertEqual("sensor.orphan", result["failed"][0]["entity_id"])
        self.assertIn("sikertelen", result["message"])


if __name__ == "__main__":
    unittest.main()
