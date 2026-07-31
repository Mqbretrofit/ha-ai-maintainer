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
                "entity_id": "sensor.xtend_removed",
                "state": "unavailable",
                "attributes": {
                    "friendly_name": "Removed Tuya sensor",
                    "restored": True,
                },
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
                "entity_id": "sensor.xtend_removed",
                "config_entry_id": "active-entry",
                "platform": "xtend_tuya",
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
    def test_all_unavailable_registry_entries_are_classified(self):
        candidates = find_entity_cleanup_candidates(
            FakeRegistryClient(),
            now=datetime(2026, 7, 30, tzinfo=UTC),
        )

        self.assertEqual(
            [
                "sensor.long_unavailable",
                "sensor.orphan",
                "sensor.xtend_removed",
                "sensor.active_but_offline",
                "sensor.yaml_sensor",
            ],
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
        active = next(
            item
            for item in candidates
            if item["entity_id"] == "sensor.active_but_offline"
        )
        self.assertEqual("manual_review", active["kind"])
        self.assertEqual("manual", active["review_level"])
        not_provided = next(
            item
            for item in candidates
            if item["entity_id"] == "sensor.xtend_removed"
        )
        self.assertEqual("not_provided", not_provided["kind"])
        self.assertEqual("confirmed", not_provided["review_level"])
        self.assertEqual("xtend_tuya", not_provided["platform"])
        self.assertIn("Home Assistant", not_provided["reason"])
        yaml = next(
            item
            for item in candidates
            if item["entity_id"] == "sensor.yaml_sensor"
        )
        self.assertIn("YAML", yaml["reason"])
        self.assertNotIn(
            "sensor.healthy", [item["entity_id"] for item in candidates]
        )

    def test_delete_revalidates_candidate_before_removal(self):
        client = FakeRegistryClient()

        result = delete_entity_cleanup_candidates(client, ["sensor.orphan"])

        self.assertEqual(["sensor.orphan"], client.removed)
        self.assertEqual(1, result["count"])

    def test_delete_allows_explicitly_selected_active_unavailable_entry(self):
        client = FakeRegistryClient()

        result = delete_entity_cleanup_candidates(
            client, ["sensor.active_but_offline"]
        )

        self.assertEqual(["sensor.active_but_offline"], client.removed)
        self.assertEqual(1, result["count"])

    def test_delete_allows_explicitly_selected_yaml_registry_entry(self):
        client = FakeRegistryClient()

        result = delete_entity_cleanup_candidates(client, ["sensor.yaml_sensor"])

        self.assertEqual(["sensor.yaml_sensor"], client.removed)
        self.assertEqual(1, result["count"])

    def test_delete_allows_home_assistant_not_provided_entry(self):
        client = FakeRegistryClient()

        result = delete_entity_cleanup_candidates(
            client, ["sensor.xtend_removed"]
        )

        self.assertEqual(["sensor.xtend_removed"], client.removed)
        self.assertEqual(1, result["count"])

    def test_delete_rejects_entry_that_is_no_longer_unavailable(self):
        client = FakeRegistryClient()
        for state in client.states:
            if state["entity_id"] == "sensor.active_but_offline":
                state["state"] = "12"

        with self.assertRaisesRegex(EntityCleanupError, "már nem unavailable"):
            delete_entity_cleanup_candidates(
                client, ["sensor.active_but_offline"]
            )

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
