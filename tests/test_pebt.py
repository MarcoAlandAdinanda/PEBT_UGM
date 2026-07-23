import copy
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from experiment import ConfigurationError, ExperimentConfig, ExperimentLogger


PEBT_CONFIG = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "pebt_yamawaki_2023_draft.json"
)


class PaperDerivedPebtTests(unittest.TestCase):
    def test_paper_configuration_loads_as_explicit_draft(self):
        config = ExperimentConfig.load(PEBT_CONFIG)

        self.assertEqual(config.task_type, "pebt")
        self.assertEqual(config.protocol_status, "draft")
        self.assertEqual(
            config.participant_conditions,
            ("interactive_agent", "non_interactive_agent"),
        )
        self.assertEqual(config.trial_count, 49)
        self.assertEqual(
            [page.page_id for page in config.instruction_pages],
            ["task-overview", "environmental-tradeoff", "response-and-blocks"],
        )
        self.assertEqual(
            [(block.block_id, len(block.trials)) for block in config.blocks],
            [
                ("lamp-confirmation", 1),
                ("set1-12-lights", 12),
                ("set1-4-lights", 12),
                ("set2-12-lights", 12),
                ("set2-4-lights", 12),
            ],
        )
        paper_urls = {
            source.url
            for source in config.sources
            if source.source_type == "research_paper"
        }
        self.assertIn(
            "https://doi.org/10.1016/j.jenvp.2023.101999",
            paper_urls,
        )

    def test_each_set_matches_paper_frequency_margins(self):
        config = ExperimentConfig.load(PEBT_CONFIG)
        pebt_trials = [
            trial
            for block in config.blocks
            for trial in block.trials
            if trial.metadata.get("trial_role") == "pebt_choice"
        ]
        self.assertEqual(len(pebt_trials), 48)

        for set_id in ("SET1", "SET2"):
            set_trials = [
                trial
                for trial in pebt_trials
                if trial.metadata["set_id"] == set_id
            ]
            self.assertEqual(len(set_trials), 24)
            self.assertEqual(
                Counter(
                    trial.metadata["dift_wait_seconds"] for trial in set_trials
                ),
                Counter({5: 8, 10: 4, 15: 4, 20: 4, 25: 4}),
            )
            self.assertEqual(
                Counter(
                    trial.metadata["time_difference_seconds"]
                    for trial in set_trials
                ),
                Counter({0: 2, 5: 8, 10: 10, 15: 4}),
            )
            self.assertEqual(
                Counter(trial.metadata["light_count"] for trial in set_trials),
                Counter({12: 12, 4: 12}),
            )

    def test_choice_and_waiting_branches_map_to_expected_relays(self):
        config = ExperimentConfig.load(PEBT_CONFIG)
        trials_by_light_count = {}
        for block in config.blocks:
            for trial in block.trials:
                if trial.metadata.get("trial_role") == "pebt_choice":
                    trials_by_light_count.setdefault(
                        trial.metadata["light_count"], trial
                    )

        twelve_light_trial = trials_by_light_count[12]
        choice, sest_wait, dift_wait = twelve_light_trial.phases
        self.assertIsNone(choice.duration_ms)
        self.assertTrue(choice.end_on_response)
        self.assertEqual(choice.allowed_keys, ("left", "right"))
        self.assertEqual(sest_wait.run_if_response_key, "left")
        self.assertEqual(sest_wait.relay_states, (0, 0, 0, 0))
        self.assertEqual(dift_wait.run_if_response_key, "right")
        self.assertEqual(dift_wait.relay_states, (1, 1, 1, 0))
        response_details = twelve_light_trial.metadata["response_details"]
        self.assertEqual(response_details["left"]["set_id"], "SET1")
        self.assertEqual(
            response_details["left"]["selected_wait_ms"],
            twelve_light_trial.metadata["sest_wait_seconds"] * 1000,
        )
        self.assertEqual(
            response_details["right"]["selected_wait_ms"],
            twelve_light_trial.metadata["dift_wait_seconds"] * 1000,
        )

        four_light_trial = trials_by_light_count[4]
        self.assertEqual(four_light_trial.phases[2].relay_states, (0, 0, 1, 0))
        for block in config.blocks:
            for trial in block.trials:
                for phase in trial.phases:
                    self.assertEqual(phase.relay_states[3], 0)

    def test_generated_pairing_and_participant_order_are_deterministic(self):
        first = ExperimentConfig.load(PEBT_CONFIG)
        second = ExperimentConfig.load(PEBT_CONFIG)
        first_pairs = [
            (
                trial.trial_id,
                trial.metadata.get("dift_wait_seconds"),
                trial.metadata.get("time_difference_seconds"),
            )
            for block in first.blocks
            for trial in block.trials
        ]
        second_pairs = [
            (
                trial.trial_id,
                trial.metadata.get("dift_wait_seconds"),
                trial.metadata.get("time_difference_seconds"),
            )
            for block in second.blocks
            for trial in block.trials
        ]
        self.assertEqual(first_pairs, second_pairs)
        self.assertEqual(
            [item.trial.trial_id for item in first.compile_trials("P001")],
            [item.trial.trial_id for item in second.compile_trials("P001")],
        )

    def test_generator_rejects_mismatched_frequency_totals(self):
        data = json.loads(PEBT_CONFIG.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(data)
        invalid["generator"]["time_difference_seconds"]["15"] = 3
        with self.assertRaises(ConfigurationError):
            ExperimentConfig.from_dict(invalid)

    def test_full_compiled_session_produces_paper_primary_measure(self):
        config = ExperimentConfig.load(PEBT_CONFIG)
        compiled_trials = config.compile_trials("P-FULL-AUDIT")
        target_sest_counts = {"SET1": 9, "SET2": 15}
        observed_choices = {"SET1": 0, "SET2": 0}

        with tempfile.TemporaryDirectory() as temp_directory:
            logger = ExperimentLogger(
                config,
                participant_id="P-FULL-AUDIT",
                participant_condition="interactive_agent",
                output_directory=temp_directory,
                compiled_trials=compiled_trials,
            )
            for item in compiled_trials:
                trial = item.trial
                if trial.metadata.get("trial_role") == "pebt_choice":
                    set_id = trial.metadata["set_id"]
                    key = (
                        "left"
                        if observed_choices[set_id] < target_sest_counts[set_id]
                        else "right"
                    )
                    if key == "left":
                        observed_choices[set_id] += 1
                    logger.log(
                        "response",
                        block_index=item.block_index,
                        block_id=item.block_id,
                        repetition=item.repetition,
                        trial_index=item.trial_index,
                        trial_id=trial.trial_id,
                        condition=trial.condition,
                        response_key=key,
                        details=trial.metadata["response_details"][key],
                    )
                logger.log(
                    "trial_end",
                    block_index=item.block_index,
                    block_id=item.block_id,
                    repetition=item.repetition,
                    trial_index=item.trial_index,
                    trial_id=trial.trial_id,
                    condition=trial.condition,
                )
            logger.finalize("completed")
            summary_path = logger.summary_path
            logger.close()

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            metrics = summary["metrics"]
            self.assertEqual(metrics["planned_trial_count"], 49)
            self.assertEqual(metrics["completed_trial_count"], 49)
            self.assertEqual(metrics["response_count"], 48)
            self.assertEqual(
                metrics["choice_counts_by_set"],
                {
                    "SET1": {"SEST": 9, "DIFT": 15},
                    "SET2": {"SEST": 15, "DIFT": 9},
                },
            )
            self.assertEqual(metrics["pebt_improvement_set2_minus_set1"], 6)


if __name__ == "__main__":
    unittest.main()
