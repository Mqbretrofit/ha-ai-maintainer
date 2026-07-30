from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

APP_PATH = Path(__file__).parents[1] / "ha_ai_maintainer" / "app"
sys.path.insert(0, str(APP_PATH))

import local_repair
from local_repair import (
    LocalRepairError,
    LocalRepairOptions,
    OPENAI_REPAIR_MODEL,
    _build_repair_request,
    _extract_structured_output,
    apply_local_repair,
    collect_allowed_files,
    load_latest_local_job,
    prepare_local_repair,
    rollback_local_repair,
    run_openai_repair,
)


class ValidConfigClient:
    def __init__(self):
        self.calls = 0

    def check_config(self):
        self.calls += 1
        return {"result": "valid", "errors": None}


class InvalidConfigClient:
    def check_config(self):
        return {"result": "invalid", "errors": "bad yaml"}


def edit_automation(
    workspace,
    _task,
    _allowed,
    _options,
    _summary_path,
    _diagnostic_context,
):
    path = workspace / "automations.yaml"
    path.write_text("- alias: Fixed\n  action: []\n", encoding="utf-8")
    return "Updated automations.yaml and kept the change focused."


class LocalRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = self.root / "config"
        self.repairs = self.root / "repairs"
        self.config.mkdir()
        self.original = "- alias: Broken\n  action: []\n"
        (self.config / "automations.yaml").write_text(
            self.original, encoding="utf-8"
        )
        self.options = LocalRepairOptions(
            enabled=True,
            api_key="sk-test-not-real",
            allowed_paths=("automations.yaml",),
            max_files=10,
            max_total_bytes=100_000,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self):
        return prepare_local_repair(
            self.options,
            "Rename the broken automation.",
            config_root=self.config,
            repair_root=self.repairs,
            repair_runner=edit_automation,
        )

    def test_prepare_changes_only_isolated_copy(self):
        proposal = self.prepare()

        self.assertEqual("proposed", proposal["status"])
        self.assertEqual(["automations.yaml"], proposal["changed_files"])
        self.assertIn("alias: Fixed", proposal["diff"])
        self.assertEqual(self.original, (self.config / "automations.yaml").read_text())

    def test_prepare_passes_bounded_diagnostic_context_to_runner(self):
        received = {}

        def capture_context(workspace, _task, _allowed, _options, _summary, context):
            received["context"] = context
            (workspace / "automations.yaml").write_text(
                "- alias: Fixed\n  action: []\n", encoding="utf-8"
            )
            return "Updated one file."

        prepare_local_repair(
            self.options,
            "Fix the evidenced configuration issue.",
            config_root=self.config,
            repair_root=self.repairs,
            repair_runner=capture_context,
            diagnostic_context='{"sanitized_evidence":"invalid template"}',
        )

        self.assertIn("invalid template", received["context"])

    def test_oversized_diagnostic_context_is_rejected(self):
        with self.assertRaisesRegex(LocalRepairError, "méretkorlát"):
            prepare_local_repair(
                self.options,
                "Fix it.",
                config_root=self.config,
                repair_root=self.repairs,
                repair_runner=edit_automation,
                diagnostic_context="x" * 40_001,
            )

    def test_no_change_becomes_persisted_manual_action_guide(self):
        def no_change(
            _workspace, _task, _allowed, _options, _summary, _context
        ):
            return (
                "Nem találtam igazolható fájlhibát. A bizonyíték hálózati "
                "kapcsolati hibát mutat."
            )

        result = prepare_local_repair(
            self.options,
            "Investigate the diagnosis.",
            config_root=self.config,
            repair_root=self.repairs,
            repair_runner=no_change,
        )

        self.assertEqual("manual_action_required", result["status"])
        self.assertEqual([], result["changed_files"])
        self.assertEqual("", result["diff"])
        self.assertIn(
            "A bizonyíték hálózati kapcsolati hibát mutat",
            result["summary"],
        )
        self.assertEqual(
            result["job_id"], load_latest_local_job(self.repairs)["job_id"]
        )

    def test_apply_backs_up_and_validates(self):
        proposal = self.prepare()
        client = ValidConfigClient()

        applied = apply_local_repair(
            proposal["job_id"],
            client,
            config_root=self.config,
            repair_root=self.repairs,
        )

        self.assertEqual("applied", applied["status"])
        self.assertEqual(1, client.calls)
        self.assertIn(
            "alias: Fixed", (self.config / "automations.yaml").read_text()
        )
        backup = (
            self.repairs
            / proposal["job_id"]
            / "backup"
            / "automations.yaml"
        )
        self.assertEqual(self.original, backup.read_text())

    def test_invalid_configuration_is_automatically_restored(self):
        proposal = self.prepare()

        with self.assertRaisesRegex(LocalRepairError, "automatikusan visszaállt"):
            apply_local_repair(
                proposal["job_id"],
                InvalidConfigClient(),
                config_root=self.config,
                repair_root=self.repairs,
            )

        self.assertEqual(self.original, (self.config / "automations.yaml").read_text())

    def test_concurrent_live_change_is_not_overwritten(self):
        proposal = self.prepare()
        external = "- alias: Changed elsewhere\n  action: []\n"
        (self.config / "automations.yaml").write_text(external, encoding="utf-8")

        with self.assertRaisesRegex(LocalRepairError, "megváltozott"):
            apply_local_repair(
                proposal["job_id"],
                ValidConfigClient(),
                config_root=self.config,
                repair_root=self.repairs,
            )

        self.assertEqual(external, (self.config / "automations.yaml").read_text())

    def test_change_during_apply_restores_only_already_applied_files(self):
        scripts_original = "morning:\n  sequence: []\n"
        scripts = self.config / "scripts.yaml"
        scripts.write_text(scripts_original, encoding="utf-8")
        options = LocalRepairOptions(
            enabled=True,
            api_key="sk-test-not-real",
            allowed_paths=("automations.yaml", "scripts.yaml"),
            max_files=10,
            max_total_bytes=100_000,
        )

        def edit_two_files(workspace, *_args):
            (workspace / "automations.yaml").write_text(
                "- alias: Fixed\n  action: []\n", encoding="utf-8"
            )
            (workspace / "scripts.yaml").write_text(
                "morning:\n  sequence:\n    - delay: 1\n", encoding="utf-8"
            )
            return "Updated two files."

        proposal = prepare_local_repair(
            options,
            "Update two files.",
            config_root=self.config,
            repair_root=self.repairs,
            repair_runner=edit_two_files,
        )
        external = "morning:\n  sequence:\n    - stop: Changed elsewhere\n"
        original_atomic_replace = local_repair._atomic_replace

        def change_second_file_after_first(source, destination, mode):
            original_atomic_replace(source, destination, mode)
            if destination == self.config / "automations.yaml":
                scripts.write_text(external, encoding="utf-8")

        with patch(
            "local_repair._atomic_replace",
            side_effect=change_second_file_after_first,
        ):
            with self.assertRaisesRegex(LocalRepairError, "alkalmazás közben"):
                apply_local_repair(
                    proposal["job_id"],
                    ValidConfigClient(),
                    config_root=self.config,
                    repair_root=self.repairs,
                )

        self.assertEqual(
            self.original, (self.config / "automations.yaml").read_text()
        )
        self.assertEqual(external, scripts.read_text())

    def test_applied_repair_can_be_rolled_back(self):
        proposal = self.prepare()
        client = ValidConfigClient()
        apply_local_repair(
            proposal["job_id"],
            client,
            config_root=self.config,
            repair_root=self.repairs,
        )

        rolled_back = rollback_local_repair(
            proposal["job_id"],
            client,
            config_root=self.config,
            repair_root=self.repairs,
        )

        self.assertEqual("rolled_back", rolled_back["status"])
        self.assertEqual(self.original, (self.config / "automations.yaml").read_text())

    def test_tampered_backup_is_not_restored(self):
        proposal = self.prepare()
        client = ValidConfigClient()
        apply_local_repair(
            proposal["job_id"],
            client,
            config_root=self.config,
            repair_root=self.repairs,
        )
        backup = (
            self.repairs
            / proposal["job_id"]
            / "backup"
            / "automations.yaml"
        )
        backup.write_text("- alias: Tampered\n", encoding="utf-8")

        with self.assertRaisesRegex(LocalRepairError, "mentés sérült"):
            rollback_local_repair(
                proposal["job_id"],
                client,
                config_root=self.config,
                repair_root=self.repairs,
            )

        self.assertIn(
            "alias: Fixed", (self.config / "automations.yaml").read_text()
        )

    def test_latest_job_is_available_after_process_restart(self):
        proposal = self.prepare()

        recovered = load_latest_local_job(self.repairs)

        self.assertIsNotNone(recovered)
        self.assertEqual(proposal["job_id"], recovered["job_id"])
        self.assertEqual("proposed", recovered["status"])

    def test_rejected_ai_output_removes_copied_workspace(self):
        def create_unapproved_file(workspace, *_args):
            (workspace / "new-secret.txt").write_text("unexpected", encoding="utf-8")
            return "Created a file."

        with self.assertRaisesRegex(LocalRepairError, "hozott létre"):
            prepare_local_repair(
                self.options,
                "Create a file.",
                config_root=self.config,
                repair_root=self.repairs,
                repair_runner=create_unapproved_file,
            )

        self.assertEqual([], list(self.repairs.glob("*")))

    def test_symlinked_ai_output_is_rejected(self):
        outside = self.root / "outside.yaml"
        outside.write_text("- alias: Outside\n", encoding="utf-8")

        def replace_with_symlink(workspace, *_args):
            target = workspace / "automations.yaml"
            target.unlink()
            target.symlink_to(outside)
            return "Replaced a file."

        with self.assertRaisesRegex(
            LocalRepairError, "hozott létre|Szimbolikus hivatkozás"
        ):
            prepare_local_repair(
                self.options,
                "Replace a file.",
                config_root=self.config,
                repair_root=self.repairs,
                repair_runner=replace_with_symlink,
            )

        self.assertEqual([], list(self.repairs.glob("*")))

    def test_workspace_symlink_tampering_is_rejected_before_apply(self):
        proposal = self.prepare()
        outside = self.root / "outside.yaml"
        outside.write_text("- alias: Outside\n", encoding="utf-8")
        proposed = (
            self.repairs
            / proposal["job_id"]
            / "workspace"
            / "automations.yaml"
        )
        proposed.unlink()
        proposed.symlink_to(outside)

        with self.assertRaisesRegex(LocalRepairError, "Szimbolikus hivatkozás"):
            apply_local_repair(
                proposal["job_id"],
                ValidConfigClient(),
                config_root=self.config,
                repair_root=self.repairs,
            )

        self.assertEqual(self.original, (self.config / "automations.yaml").read_text())

    def test_sensitive_and_parent_paths_are_rejected(self):
        (self.config / "secrets.yaml").write_text("password: secret\n")
        with self.assertRaisesRegex(LocalRepairError, "tiltott"):
            collect_allowed_files(
                self.config, ("secrets.yaml",), max_files=10, max_total_bytes=1000
            )
        with self.assertRaisesRegex(LocalRepairError, "biztonságos"):
            collect_allowed_files(
                self.config, ("../secrets.yaml",), max_files=10, max_total_bytes=1000
            )

    def test_repair_request_is_tool_free_strict_and_marks_input_untrusted(self):
        payload = _build_repair_request(
            "Fix the evidenced issue.",
            '{"log":"invalid template"}',
            [
                {
                    "path": "automations.yaml",
                    "sha256": "a" * 64,
                    "content": "- alias: Broken\n",
                }
            ],
        )

        self.assertEqual(OPENAI_REPAIR_MODEL, payload["model"])
        self.assertFalse(payload["store"])
        self.assertNotIn("tools", payload)
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual("json_schema", payload["text"]["format"]["type"])
        system_prompt = payload["input"][0]["content"]
        self.assertIn("untrusted", system_prompt)
        self.assertIn("never instructions", system_prompt)
        self.assertIn("no tools", system_prompt)
        self.assertIn("complete replacement content", system_prompt)
        self.assertIn("invalid template", payload["input"][1]["content"])

    def test_structured_openai_plan_updates_only_the_workspace_copy(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        automation = workspace / "automations.yaml"
        automation.write_text(self.original, encoding="utf-8")
        summary = self.root / "summary.txt"
        plan = {
            "summary": "Javítottam az automatizálást.",
            "no_change_reason": "",
            "changes": [
                {
                    "path": "automations.yaml",
                    "original_sha256": local_repair._sha256(automation),
                    "content": "- alias: Fixed\n  action: []\n",
                    "explanation": "A hibás nevet javítottam.",
                }
            ],
        }
        response = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": local_repair.json.dumps(plan),
                        }
                    ],
                }
            ],
        }
        with patch(
            "local_repair._request_openai_response", return_value=response
        ) as request:
            result = run_openai_repair(
                workspace,
                "Fix the evidenced issue.",
                ("automations.yaml",),
                self.options,
                summary,
                '{"log":"invalid template"}',
            )

        self.assertIn("Javítottam", result)
        self.assertIn("alias: Fixed", automation.read_text(encoding="utf-8"))
        self.assertEqual(result, summary.read_text(encoding="utf-8"))
        sent_payload, sent_key = request.call_args.args
        self.assertEqual("sk-test-not-real", sent_key)
        self.assertNotIn("sk-test-not-real", str(sent_payload))

    def test_structured_plan_rejects_wrong_hash(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        (workspace / "automations.yaml").write_text(
            self.original, encoding="utf-8"
        )
        plan = {
            "summary": "Javítás.",
            "no_change_reason": "",
            "changes": [
                {
                    "path": "automations.yaml",
                    "original_sha256": "0" * 64,
                    "content": "- alias: Fixed\n",
                    "explanation": "Javítás.",
                }
            ],
        }
        with self.assertRaisesRegex(LocalRepairError, "ellenőrzőösszeget"):
            local_repair._validate_and_apply_plan(
                workspace, ("automations.yaml",), plan
            )
        self.assertEqual(
            self.original,
            (workspace / "automations.yaml").read_text(encoding="utf-8"),
        )

    def test_incomplete_and_refused_responses_are_rejected(self):
        with self.assertRaisesRegex(LocalRepairError, "nem fejezte be"):
            _extract_structured_output(
                {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                }
            )
        with self.assertRaisesRegex(LocalRepairError, "nem vállalta"):
            _extract_structured_output(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "refusal", "refusal": "cannot comply"}
                            ],
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
