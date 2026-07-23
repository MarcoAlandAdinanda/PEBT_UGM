import tempfile
import unittest
from pathlib import Path

from experiment_builder import ExperimentDraft
from gui import DemoRelayController, LocalWebApplication


PEBT_CONFIG = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "pebt_yamawaki_2023_draft.json"
)


class ExperimentDraftTests(unittest.TestCase):
    def test_new_draft_is_immediately_valid_and_editable(self):
        draft = ExperimentDraft.new()

        config = draft.validate()

        self.assertEqual(config.protocol_id, "NEW-EXPERIMENT-V1")
        self.assertEqual(len(config.blocks), 1)
        self.assertEqual(config.trial_count, 1)
        self.assertFalse(draft.is_dirty)

    def test_hierarchy_operations_preserve_unique_ids(self):
        draft = ExperimentDraft.new()

        second_block = draft.add_block()
        second_trial = draft.add_trial(second_block[0])
        second_phase = draft.add_phase(*second_trial)
        copied_trial = draft.duplicate("trial", second_trial)
        copied_block = draft.duplicate("block", second_block)

        self.assertEqual(second_phase, (1, 1, 1))
        self.assertEqual(copied_trial, (1, 2))
        self.assertEqual(copied_block, (2,))
        block_ids = [block["block_id"] for block in draft.data["blocks"]]
        trial_ids = [
            trial["trial_id"]
            for block in draft.data["blocks"]
            for trial in block["trials"]
        ]
        self.assertEqual(len(block_ids), len(set(block_ids)))
        self.assertEqual(len(trial_ids), len(set(trial_ids)))
        draft.validate()

    def test_move_delete_and_structural_edit_reset_validated_status(self):
        draft = ExperimentDraft.new()
        draft.data["protocol_status"] = "validated"
        second_trial = draft.add_trial(0)

        self.assertEqual(draft.data["protocol_status"], "draft")
        moved = draft.move("trial", second_trial, -1)
        self.assertEqual(moved, (0, 0))
        self.assertEqual(draft.data["blocks"][0]["trials"][0]["trial_id"], "trial")

        parent = draft.delete("trial", moved)

        self.assertEqual(parent, ("block", (0,)))
        self.assertEqual(draft.validate().trial_count, 1)

    def test_editing_validated_experiment_properties_returns_it_to_draft(self):
        draft = ExperimentDraft.new()
        draft.data["protocol_status"] = "validated"
        replacement = dict(draft.data)
        replacement["title"] = "Changed after validation"

        draft.replace_node("experiment", (), replacement)

        self.assertEqual(draft.data["protocol_status"], "draft")

        approved = dict(draft.data)
        approved["protocol_status"] = "validated"
        draft.replace_node("experiment", (), approved)
        self.assertEqual(draft.data["protocol_status"], "validated")

    def test_save_and_load_round_trip(self):
        draft = ExperimentDraft.new()
        draft.data["title"] = "Saved builder experiment"
        draft._touch()

        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "nested" / "experiment.json"
            saved_path = draft.save(destination)
            loaded = ExperimentDraft.load(saved_path)

            self.assertEqual(saved_path, destination.resolve())
            self.assertFalse(draft.is_dirty)
            self.assertFalse(loaded.is_dirty)
            self.assertEqual(loaded.data, draft.data)
            self.assertEqual(loaded.validate().title, "Saved builder experiment")
            self.assertFalse((destination.parent / "experiment.json.tmp").exists())

    def test_compact_pebt_source_opens_as_expanded_save_as_copy(self):
        draft = ExperimentDraft.load(PEBT_CONFIG)

        self.assertTrue(draft.expanded_from_generator)
        self.assertIsNone(draft.file_path)
        self.assertEqual(draft.source_path, PEBT_CONFIG.resolve())
        self.assertNotIn("generator", draft.data)
        self.assertEqual(draft.validate().trial_count, 49)

        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "expanded.json"
            draft.save(destination)

            self.assertFalse(draft.expanded_from_generator)
            self.assertEqual(draft.file_path, destination.resolve())
            self.assertEqual(ExperimentDraft.load(destination).validate().trial_count, 49)


class BuilderApplicationIntegrationTests(unittest.TestCase):
    def test_application_exposes_build_execute_and_manual_modes(self):
        app = LocalWebApplication(
            controller=DemoRelayController(),
            demo_mode=True,
        )
        try:
            shell = (
                Path(__file__).resolve().parents[1]
                / "web"
                / "index.html"
            ).read_text(encoding="utf-8")
            self.assertIn("Build Experiment", shell)
            self.assertIn('data-view="execute"', shell)
            self.assertIn('data-view="manual"', shell)

            loaded = app.load_config(
                "configs/pebt_yamawaki_2023_draft.json",
                builder=True,
            )
            self.assertTrue(loaded["expanded_from_generator"])
            self.assertEqual(loaded["summary"]["trial_count"], 49)
            self.assertEqual(app.system_payload()["mode"], "demo")
        finally:
            app.shutdown()


if __name__ == "__main__":
    unittest.main()
