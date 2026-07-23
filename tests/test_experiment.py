import csv
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from experiment import ConfigurationError, ExperimentConfig, ExperimentLogger


DEMO_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "demo_experiment.json"


def minimal_config():
    return {
        "schema_version": 1,
        "protocol_id": "TEST-V1",
        "title": "Test protocol",
        "protocol_status": "draft",
        "description": "",
        "instructions": "Press space.",
        "random_seed": 17,
        "data_directory": "data/experiments",
        "display": {
            "fullscreen": False,
            "background": "#000000",
            "foreground": "#FFFFFF",
            "font_size": 30,
        },
        "sources": [],
        "blocks": [
            {
                "block_id": "block-a",
                "instructions": "Block instructions",
                "repetitions": 2,
                "randomize_trials": True,
                "trials": [
                    {
                        "trial_id": "left",
                        "condition": "left",
                        "correct_key": "space",
                        "phases": [
                            {
                                "name": "stimulus",
                                "duration_ms": 100,
                                "text": "Respond",
                                "lights": ["left"],
                                "collect_response": True,
                                "allowed_keys": ["space"],
                            }
                        ],
                    },
                    {
                        "trial_id": "front",
                        "condition": "front",
                        "correct_key": "space",
                        "phases": [
                            {
                                "name": "stimulus",
                                "duration_ms": 150,
                                "text": "Respond",
                                "lights": ["front"],
                                "collect_response": True,
                                "allowed_keys": ["space"],
                            }
                        ],
                    },
                ],
            }
        ],
    }


class ExperimentConfigTests(unittest.TestCase):
    def test_demo_configuration_loads_and_is_explicitly_non_research(self):
        config = ExperimentConfig.load(DEMO_CONFIG)
        self.assertEqual(config.protocol_status, "demo")
        self.assertIn("DEMO ONLY", config.description)
        self.assertEqual(config.trial_count, 3)
        self.assertEqual(config.estimated_duration_ms, 6600)

    def test_compilation_is_deterministic_for_participant(self):
        config = ExperimentConfig.from_dict(minimal_config())
        first = config.compile_trials("P001")
        second = config.compile_trials("P001")
        self.assertEqual(
            [item.trial.trial_id for item in first],
            [item.trial.trial_id for item in second],
        )
        self.assertEqual(len(first), 4)
        self.assertEqual([item.trial_index for item in first], [1, 2, 3, 4])

    def test_phase_maps_named_light_to_relay_output(self):
        config = ExperimentConfig.from_dict(minimal_config())
        trials = {
            item.trial.trial_id: item for item in config.compile_trials("P001")
        }
        self.assertEqual(trials["left"].trial.phases[0].relay_states, (1, 0, 0, 0))
        self.assertEqual(trials["front"].trial.phases[0].relay_states, (0, 0, 1, 0))

    def test_instruction_pages_are_validated_with_backward_compatible_default(self):
        default_config = ExperimentConfig.from_dict(minimal_config())
        self.assertEqual(len(default_config.instruction_pages), 1)
        self.assertEqual(default_config.instruction_pages[0].page_id, "overview")
        self.assertEqual(
            default_config.instruction_pages[0].text,
            default_config.instructions,
        )

        data = minimal_config()
        data["instruction_pages"] = [
            {"page_id": "one", "title": "Page one", "text": "First"},
            {
                "page_id": "two",
                "title": "Page two",
                "text": "Second",
                "hint": "Continue",
            },
        ]
        config = ExperimentConfig.from_dict(data)
        self.assertEqual(
            [page.page_id for page in config.instruction_pages],
            ["one", "two"],
        )
        self.assertEqual(config.instruction_pages[1].hint, "Continue")

        data["instruction_pages"][1]["page_id"] = "one"
        with self.assertRaises(ConfigurationError):
            ExperimentConfig.from_dict(data)

    def test_unknown_light_side_is_rejected(self):
        data = minimal_config()
        data["blocks"][0]["trials"][0]["phases"][0]["lights"] = ["back"]
        with self.assertRaises(ConfigurationError):
            ExperimentConfig.from_dict(data)

    def test_duplicate_trial_id_is_rejected(self):
        data = minimal_config()
        data["blocks"][0]["trials"][1]["trial_id"] = "left"
        with self.assertRaises(ConfigurationError):
            ExperimentConfig.from_dict(data)

    def test_response_phase_requires_allowed_keys(self):
        data = minimal_config()
        data["blocks"][0]["trials"][0]["phases"][0]["allowed_keys"] = []
        with self.assertRaises(ConfigurationError):
            ExperimentConfig.from_dict(data)

    def test_correct_key_must_be_allowed(self):
        data = minimal_config()
        data["blocks"][0]["trials"][0]["correct_key"] = "enter"
        with self.assertRaises(ConfigurationError):
            ExperimentConfig.from_dict(data)

    def test_response_gated_phase_can_branch_without_a_timeout(self):
        data = minimal_config()
        phases = data["blocks"][0]["trials"][0]["phases"]
        phases[0]["duration_ms"] = None
        phases[0]["end_on_response"] = True
        phases.append(
            {
                "name": "selected_wait",
                "duration_ms": 250,
                "text": "Waiting",
                "lights": ["left"],
                "collect_response": False,
                "run_if_response_key": "space",
            }
        )

        config = ExperimentConfig.from_dict(data)
        trial = config.blocks[0].trials[0]
        self.assertIsNone(trial.phases[0].duration_ms)
        self.assertTrue(trial.phases[0].end_on_response)
        self.assertEqual(trial.phases[1].run_if_response_key, "space")

        invalid = minimal_config()
        invalid["blocks"][0]["trials"][0]["phases"][0]["duration_ms"] = None
        with self.assertRaises(ConfigurationError):
            ExperimentConfig.from_dict(invalid)

    def test_validated_protocol_requires_research_paper_source(self):
        data = minimal_config()
        data["protocol_status"] = "validated"
        with self.assertRaises(ConfigurationError):
            ExperimentConfig.from_dict(data)

        data["sources"] = [
            {
                "source_type": "research_paper",
                "title": "Approved study protocol",
                "citation": "Author et al. (2026)",
                "url": "https://example.org/paper.pdf",
                "pages": "4-8",
                "notes": "Trial timing and condition definitions",
            }
        ]
        config = ExperimentConfig.from_dict(data)
        self.assertEqual(config.sources[0].source_type, "research_paper")

    def test_invalid_json_has_actionable_location(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            invalid_path = Path(temp_directory) / "invalid.json"
            invalid_path.write_text('{"schema_version":', encoding="utf-8")
            with self.assertRaises(ConfigurationError) as context:
                ExperimentConfig.load(invalid_path)
            self.assertIn("line 1", str(context.exception))

    def test_loaded_configuration_records_exact_file_hash(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            config_path = Path(temp_directory) / "experiment.json"
            source_bytes = json.dumps(minimal_config(), indent=2).encode("utf-8")
            config_path.write_bytes(source_bytes)

            config = ExperimentConfig.load(config_path)

            self.assertEqual(
                config.config_sha256,
                hashlib.sha256(source_bytes).hexdigest(),
            )


class ExperimentLoggerTests(unittest.TestCase):
    def test_logger_creates_and_flushes_structured_csv(self):
        config = ExperimentConfig.from_dict(minimal_config(), source_path="config.json")
        clock_values = iter((1000000000, 1002000000))
        fixed_now = lambda: datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as temp_directory:
            logger = ExperimentLogger(
                config,
                participant_id="P/001",
                session_label="S1",
                output_directory=temp_directory,
                clock_ns=lambda: next(clock_values),
                now_utc=fixed_now,
            )
            logger.log(
                "phase_start",
                block_index=0,
                block_id="block-a",
                repetition=1,
                trial_index=1,
                trial_id="left",
                condition="left",
                phase_index=0,
                phase_name="stimulus",
                scheduled_duration_ms=100,
                lights=("left",),
                relay_state=(1, 0, 0, 0),
                details={"research_use": False},
            )
            log_path = logger.path
            self.assertTrue(log_path.exists())
            self.assertIn("P_001", log_path.name)
            self.assertTrue(logger.summary_path.exists())
            logger.close()

            with log_path.open("r", encoding="utf-8", newline="") as log_file:
                rows = list(csv.DictReader(log_file))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event"], "phase_start")
            self.assertEqual(rows[0]["participant_id"], "P/001")
            self.assertEqual(rows[0]["config_sha256"], config.config_sha256)
            self.assertEqual(json.loads(rows[0]["relay_state"]), [1, 0, 0, 0])
            self.assertEqual(json.loads(rows[0]["details_json"]), {"research_use": False})

            summary = json.loads(logger.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "in_progress")
            self.assertEqual(summary["protocol"]["config_sha256"], config.config_sha256)

    def test_logger_final_summary_contains_trial_order_and_metrics(self):
        config = ExperimentConfig.from_dict(minimal_config(), source_path="config.json")
        compiled_trials = config.compile_trials("P001")

        with tempfile.TemporaryDirectory() as temp_directory:
            logger = ExperimentLogger(
                config,
                participant_id="P001",
                session_label="S1",
                output_directory=temp_directory,
                compiled_trials=compiled_trials,
            )
            logger.log(
                "response",
                response_key="space",
                response_time_ms=250.0,
                correct=True,
                details={
                    "choice_label": "SEST",
                    "pro_environmental": True,
                },
            )
            logger.log("response_timeout")
            logger.log("trial_end")
            logger.finalize("completed")
            logger.close()

            summary = json.loads(logger.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(len(summary["trial_order"]), 4)
            self.assertEqual(summary["metrics"]["planned_trial_count"], 4)
            self.assertEqual(summary["metrics"]["completed_trial_count"], 1)
            self.assertEqual(summary["metrics"]["response_count"], 1)
            self.assertEqual(summary["metrics"]["response_timeout_count"], 1)
            self.assertEqual(summary["metrics"]["accuracy_percent"], 100.0)
            self.assertEqual(summary["metrics"]["mean_response_time_ms"], 250.0)
            self.assertEqual(summary["metrics"]["choice_counts"], {"SEST": 1})
            self.assertEqual(
                summary["metrics"]["pro_environmental_choice_percent"],
                100.0,
            )

    def test_logger_requires_and_records_participant_condition(self):
        data = minimal_config()
        data["participant_conditions"] = ["interactive", "non_interactive"]
        config = ExperimentConfig.from_dict(data)

        with tempfile.TemporaryDirectory() as temp_directory:
            with self.assertRaises(ConfigurationError):
                ExperimentLogger(
                    config,
                    participant_id="P001",
                    output_directory=temp_directory,
                )

            logger = ExperimentLogger(
                config,
                participant_id="P001",
                participant_condition="interactive",
                output_directory=temp_directory,
            )
            logger.log("session_start")
            logger.finalize("completed")
            logger.close()

            with logger.path.open("r", encoding="utf-8", newline="") as log_file:
                row = next(csv.DictReader(log_file))
            self.assertEqual(row["participant_condition"], "interactive")
            summary = json.loads(logger.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["participant_condition"], "interactive")

    def test_logger_computes_paper_primary_pebt_improvement_metric(self):
        config = ExperimentConfig.from_dict(minimal_config())

        with tempfile.TemporaryDirectory() as temp_directory:
            logger = ExperimentLogger(
                config,
                participant_id="P001",
                output_directory=temp_directory,
            )
            for set_id, sest_count, dift_count in (
                ("SET1", 10, 14),
                ("SET2", 16, 8),
            ):
                for _ in range(sest_count):
                    logger.log(
                        "response",
                        details={
                            "set_id": set_id,
                            "choice_label": "SEST",
                            "pro_environmental": True,
                        },
                    )
                for _ in range(dift_count):
                    logger.log(
                        "response",
                        details={
                            "set_id": set_id,
                            "choice_label": "DIFT",
                            "pro_environmental": False,
                        },
                    )
            metrics = logger.summary
            logger.close()

            self.assertEqual(
                metrics["choice_counts_by_set"],
                {
                    "SET1": {"SEST": 10, "DIFT": 14},
                    "SET2": {"SEST": 16, "DIFT": 8},
                },
            )
            self.assertEqual(metrics["pebt_improvement_set2_minus_set1"], 6)

    def test_same_timestamp_creates_collision_safe_session_files(self):
        config = ExperimentConfig.from_dict(minimal_config())
        fixed_now = lambda: datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as temp_directory:
            first = ExperimentLogger(
                config,
                participant_id="P001",
                output_directory=temp_directory,
                now_utc=fixed_now,
            )
            second = ExperimentLogger(
                config,
                participant_id="P001",
                output_directory=temp_directory,
                now_utc=fixed_now,
            )
            try:
                self.assertNotEqual(first.path, second.path)
                self.assertNotEqual(first.summary_path, second.summary_path)
            finally:
                first.close()
                second.close()


if __name__ == "__main__":
    unittest.main()
