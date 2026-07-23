import csv
import json
import tempfile
import tkinter as tk
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from experiment import ExperimentConfig
from experiment_ui import ExperimentRunnerWindow
from gui import DemoRelayController


PEBT_CONFIG = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "pebt_yamawaki_2023_draft.json"
)


def runner_config():
    return ExperimentConfig.from_dict(
        {
            "schema_version": 1,
            "protocol_id": "UI-TEST",
            "title": "UI test",
            "protocol_status": "demo",
            "description": "Automated runner test",
            "instructions": "Start",
            "random_seed": 1,
            "data_directory": "data/experiments",
            "display": {
                "fullscreen": False,
                "background": "#000000",
                "foreground": "#FFFFFF",
                "font_size": 20,
            },
            "sources": [],
            "blocks": [
                {
                    "block_id": "test",
                    "instructions": "Start block",
                    "repetitions": 1,
                    "randomize_trials": False,
                    "trials": [
                        {
                            "trial_id": "trial-1",
                            "condition": "left",
                            "correct_key": "space",
                            "phases": [
                                {
                                    "name": "stimulus",
                                    "duration_ms": 40,
                                    "text": "SPACE",
                                    "lights": ["left"],
                                    "collect_response": True,
                                    "allowed_keys": ["space"],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def branching_runner_config():
    return ExperimentConfig.from_dict(
        {
            "schema_version": 1,
            "task_type": "pebt",
            "protocol_id": "BRANCH-TEST",
            "title": "Branch test",
            "protocol_status": "demo",
            "description": "Conditional response test",
            "instructions": "Start",
            "instruction_pages": [
                {"page_id": "one", "title": "One", "text": "First"},
                {"page_id": "two", "title": "Two", "text": "Second"},
            ],
            "random_seed": 1,
            "data_directory": "data/experiments",
            "participant_conditions": [
                "interactive_agent",
                "non_interactive_agent",
            ],
            "display": {
                "fullscreen": False,
                "background": "#000000",
                "foreground": "#FFFFFF",
                "font_size": 20,
            },
            "sources": [],
            "blocks": [
                {
                    "block_id": "choice",
                    "instructions": "Start block",
                    "repetitions": 1,
                    "randomize_trials": False,
                    "trials": [
                        {
                            "trial_id": "choice-1",
                            "condition": "choice",
                            "correct_key": None,
                            "metadata": {
                                "trial_role": "pebt_choice",
                                "set_id": "SET1",
                                "light_count": 12,
                                "sest_wait_seconds": 1,
                                "dift_wait_seconds": 1,
                                "time_difference_seconds": 0,
                                "co2_liters_per_hour_dift": 120,
                                "observer_label": "test observer",
                                "response_details": {
                                    "left": {
                                        "set_id": "SET1",
                                        "choice_label": "SEST",
                                        "pro_environmental": True,
                                    },
                                    "right": {
                                        "set_id": "SET1",
                                        "choice_label": "DIFT",
                                        "pro_environmental": False,
                                    },
                                }
                            },
                            "phases": [
                                {
                                    "name": "choice",
                                    "duration_ms": None,
                                    "text": "LEFT or RIGHT",
                                    "lights": [],
                                    "collect_response": True,
                                    "allowed_keys": ["left", "right"],
                                    "end_on_response": True,
                                },
                                {
                                    "name": "sest_wait",
                                    "duration_ms": 30,
                                    "text": "SEST",
                                    "lights": [],
                                    "collect_response": False,
                                    "run_if_response_key": "left",
                                },
                                {
                                    "name": "dift_wait",
                                    "duration_ms": 30,
                                    "text": "DIFT",
                                    "lights": ["left"],
                                    "collect_response": False,
                                    "run_if_response_key": "right",
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    )


def fast_pebt_config():
    config = ExperimentConfig.load(PEBT_CONFIG)
    fast_blocks = []
    for block in config.blocks:
        fast_trials = []
        for trial in block.trials:
            fast_phases = tuple(
                replace(
                    phase,
                    duration_ms=(
                        None if phase.duration_ms is None else 1
                    ),
                )
                for phase in trial.phases
            )
            fast_trials.append(replace(trial, phases=fast_phases))
        fast_blocks.append(replace(block, trials=tuple(fast_trials)))
    return replace(
        config,
        display=replace(config.display, fullscreen=False),
        blocks=tuple(fast_blocks),
    )


class ExperimentRunnerUiTests(unittest.TestCase):
    def test_runner_records_response_and_finishes_with_all_relays_off(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest("Tk display unavailable: {0}".format(exc))
        root.withdraw()
        controller = DemoRelayController()
        controller.connect()
        completion = []

        try:
            with tempfile.TemporaryDirectory() as temp_directory:
                runner = ExperimentRunnerWindow(
                    root,
                    config=runner_config(),
                    participant_id="P001",
                    session_label="S1",
                    controller=controller,
                    output_directory=temp_directory,
                    on_finished=lambda result, path: completion.append((result, path)),
                )

                runner._handle_key(SimpleNamespace(keysym="space"))
                self.assertEqual(runner._waiting_for, "block_start")
                runner._handle_key(SimpleNamespace(keysym="space"))
                self.assertEqual(runner._waiting_for, "phase")

                root.after(
                    5,
                    lambda: runner._handle_key(SimpleNamespace(keysym="space")),
                )
                root.after(150, root.quit)
                root.mainloop()

                self.assertEqual(runner._waiting_for, "complete")
                self.assertEqual(controller.last_states, (0, 0, 0, 0))
                with Path(runner.result_path).open(
                    "r", encoding="utf-8", newline=""
                ) as log_file:
                    rows = list(csv.DictReader(log_file))
                events = [row["event"] for row in rows]
                self.assertIn("block_gate_complete", events)
                self.assertIn("response", events)
                self.assertIn("session_complete", events)
                block_gate = next(
                    row for row in rows if row["event"] == "block_gate_complete"
                )
                self.assertGreaterEqual(float(block_gate["elapsed_ms"]), 0.0)
                response = next(row for row in rows if row["event"] == "response")
                self.assertEqual(response["response_key"], "space")
                self.assertEqual(response["correct"], "True")

                summary = json.loads(
                    Path(runner.summary_path).read_text(encoding="utf-8")
                )
                self.assertEqual(summary["status"], "completed")
                self.assertEqual(summary["metrics"]["completed_trial_count"], 1)
                self.assertEqual(summary["metrics"]["accuracy_percent"], 100.0)

                runner._handle_key(SimpleNamespace(keysym="Return"))
                self.assertEqual(completion[0][0], "completed")
        finally:
            root.destroy()

    def test_response_ends_choice_and_runs_only_selected_branch(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest("Tk display unavailable: {0}".format(exc))
        root.withdraw()
        controller = DemoRelayController()
        controller.connect()

        try:
            with tempfile.TemporaryDirectory() as temp_directory:
                runner = ExperimentRunnerWindow(
                    root,
                    config=branching_runner_config(),
                    participant_id="P001",
                    session_label="S1",
                    participant_condition="interactive_agent",
                    controller=controller,
                    output_directory=temp_directory,
                )
                runner._handle_key(SimpleNamespace(keysym="space"))
                self.assertEqual(runner._waiting_for, "instruction_page")
                runner._handle_key(SimpleNamespace(keysym="space"))
                self.assertEqual(runner._waiting_for, "block_start")
                runner._handle_key(SimpleNamespace(keysym="space"))
                self.assertEqual(runner._phase_index, 0)
                self.assertIsNone(runner._after_id)
                self.assertTrue(runner.pebt_canvas.winfo_manager())
                self.assertGreater(len(runner.pebt_canvas.find_all()), 20)
                runner.window.update()
                canvas_bbox = runner.pebt_canvas.bbox("all")
                self.assertGreaterEqual(canvas_bbox[0], 0)
                self.assertGreaterEqual(canvas_bbox[1], 0)
                self.assertLessEqual(canvas_bbox[2], runner.pebt_canvas.winfo_width())
                self.assertLessEqual(canvas_bbox[3], runner.pebt_canvas.winfo_height())
                rendered_text = {
                    runner.pebt_canvas.itemcget(item_id, "text")
                    for item_id in runner.pebt_canvas.find_all()
                    if runner.pebt_canvas.type(item_id) == "text"
                }
                self.assertIn("SEST", rendered_text)
                self.assertIn("DIFT", rendered_text)
                self.assertIn("PANAH KIRI", rendered_text)
                self.assertIn("PANAH KANAN", rendered_text)

                runner._handle_key(SimpleNamespace(keysym="Left"))
                self.assertEqual(runner._phase_index, 1)
                self.assertEqual(controller.last_states, (0, 0, 0, 0))

                root.after(100, root.quit)
                root.mainloop()
                self.assertEqual(runner._waiting_for, "complete")

                with Path(runner.result_path).open(
                    "r", encoding="utf-8", newline=""
                ) as log_file:
                    rows = list(csv.DictReader(log_file))
                skipped = [row for row in rows if row["event"] == "phase_skipped"]
                self.assertEqual(len(skipped), 1)
                self.assertEqual(skipped[0]["phase_name"], "dift_wait")
                self.assertEqual(
                    len(
                        [
                            row
                            for row in rows
                            if row["event"] == "instruction_page_complete"
                        ]
                    ),
                    2,
                )
                response = next(row for row in rows if row["event"] == "response")
                self.assertEqual(json.loads(response["details_json"])["choice_label"], "SEST")

                summary = json.loads(
                    Path(runner.summary_path).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    summary["metrics"]["pro_environmental_choice_count"], 1
                )
                runner._handle_key(SimpleNamespace(keysym="Return"))
        finally:
            root.destroy()

    def test_full_pebt_runner_dry_run_completes_all_trials_and_metrics(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest("Tk display unavailable: {0}".format(exc))
        root.withdraw()
        controller = DemoRelayController()
        controller.connect()

        try:
            with tempfile.TemporaryDirectory() as temp_directory:
                runner = ExperimentRunnerWindow(
                    root,
                    config=fast_pebt_config(),
                    participant_id="P-FULL-UI-AUDIT",
                    session_label="QA",
                    participant_condition="interactive_agent",
                    controller=controller,
                    output_directory=temp_directory,
                )
                step_count = 0
                while runner._waiting_for != "complete":
                    step_count += 1
                    self.assertLess(step_count, 500)
                    if runner._waiting_for in ("instruction_page", "block_start"):
                        runner._handle_key(SimpleNamespace(keysym="space"))
                        continue
                    if runner._waiting_for != "phase":
                        root.update()
                        continue
                    phase = runner._current_compiled_trial.trial.phases[
                        runner._phase_index
                    ]
                    if phase.collect_response:
                        metadata = runner._current_compiled_trial.trial.metadata
                        target_sest = 8 if metadata["set_id"] == "SET1" else 14
                        key = (
                            "Left"
                            if metadata["set_trial_index"] <= target_sest
                            else "Right"
                        )
                        runner._handle_key(SimpleNamespace(keysym=key))
                    else:
                        if runner._after_id is not None:
                            runner.window.after_cancel(runner._after_id)
                            runner._after_id = None
                        runner._finish_current_phase()

                summary = json.loads(
                    Path(runner.summary_path).read_text(encoding="utf-8")
                )
                self.assertEqual(summary["status"], "completed")
                self.assertEqual(
                    summary["metrics"]["completed_trial_count"], 49
                )
                self.assertEqual(summary["metrics"]["response_count"], 48)
                self.assertEqual(
                    summary["metrics"]["choice_counts_by_set"],
                    {
                        "SET1": {"SEST": 8, "DIFT": 16},
                        "SET2": {"SEST": 14, "DIFT": 10},
                    },
                )
                self.assertEqual(
                    summary["metrics"]["pebt_improvement_set2_minus_set1"],
                    6,
                )
                self.assertEqual(controller.last_states, (0, 0, 0, 0))
                runner._handle_key(SimpleNamespace(keysym="Return"))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
