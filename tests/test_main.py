from pathlib import Path
import json
import sys
import tempfile
import unittest

APP_PATH = Path(__file__).parents[1] / "ha_ai_maintainer" / "app"
sys.path.insert(0, str(APP_PATH))

from local_repair import LocalRepairError, LocalRepairOptions
from main import (
    ObserverState,
    load_entity_cleanup_options,
    select_local_repair_paths,
)


class MainTests(unittest.TestCase):
    def test_repair_path_selection_can_only_narrow_configured_paths(self):
        options = LocalRepairOptions(
            enabled=True,
            api_key="test",
            allowed_paths=("configuration.yaml", "packages", "www"),
        )

        selected = select_local_repair_paths(
            options, ["configuration.yaml", "packages"]
        )

        self.assertEqual(
            ("configuration.yaml", "packages"), selected.allowed_paths
        )
        with self.assertRaisesRegex(LocalRepairError, "nem engedélyezett"):
            select_local_repair_paths(options, ["secrets.yaml"])

    def test_repair_path_selection_rejects_empty_list(self):
        with self.assertRaisesRegex(LocalRepairError, "legalább egy"):
            select_local_repair_paths(LocalRepairOptions(), [])

    def test_status_does_not_expose_internal_analysis_evidence(self):
        state = ObserverState()
        state.finish_analysis(
            {
                "text": "diagnosis",
                "source_generated_at": "now",
                "evidence": {"log_samples": [{"message": "private evidence"}]},
            },
            None,
        )

        response = state.response()

        self.assertNotIn("evidence", response["analysis"])
        self.assertIn("private evidence", state.latest_repair_context())

    def test_entity_cleanup_is_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            self.assertEqual((False, 30), load_entity_cleanup_options(path))
            path.write_text(
                json.dumps(
                    {
                        "entity_cleanup_enabled": True,
                        "entity_cleanup_min_unavailable_days": 45,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual((True, 45), load_entity_cleanup_options(path))


if __name__ == "__main__":
    unittest.main()
