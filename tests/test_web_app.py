import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from experiment import ExperimentConfig
from pebt import expand_pebt_configuration
from relay_controller import DemoRelayController, RelayError
from web_app import ApiError, LocalWebApplication, create_server
from web_runtime import WebExperimentSession, WebSessionError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PEBT_CONFIG = PROJECT_ROOT / "configs" / "pebt_yamawaki_2023_draft.json"


class RecordingDemoRelayController(DemoRelayController):
    def __init__(self):
        super(RecordingDemoRelayController, self).__init__()
        self.history = []

    def set_states(self, states):
        result = super(RecordingDemoRelayController, self).set_states(states)
        self.history.append(tuple(int(value) for value in states))
        return result


class BlockingActivationDemoRelayController(RecordingDemoRelayController):
    def __init__(self):
        super(BlockingActivationDemoRelayController, self).__init__()
        self.activation_started = threading.Event()
        self.release_activation = threading.Event()

    def set_states(self, states):
        normalized = tuple(int(value) for value in states)
        if any(normalized):
            self.activation_started.set()
            if not self.release_activation.wait(2.0):
                raise RuntimeError("Timed out waiting to release relay activation")
        return super(BlockingActivationDemoRelayController, self).set_states(normalized)


class FaultInjectingDemoRelayController(DemoRelayController):
    def __init__(self):
        super(FaultInjectingDemoRelayController, self).__init__()
        self.fail_readback = False
        self.fail_off = False
        self.fail_off_error = RelayError

    def set_states(self, states):
        normalized = tuple(int(value) for value in states)
        if self.fail_off and normalized == (0, 0, 0, 0):
            raise self.fail_off_error("Injected all-off failure")
        return super(FaultInjectingDemoRelayController, self).set_states(states)

    def get_states(self):
        if self.fail_readback:
            raise RelayError("Injected readback failure")
        return super(FaultInjectingDemoRelayController, self).get_states()


def web_config(response_gated=True):
    phase = {
        "name": "response",
        "duration_ms": None if response_gated else 20,
        "text": "SPACE",
        "lights": ["left"],
        "collect_response": True,
        "allowed_keys": ["space"],
        "end_on_response": response_gated,
    }
    return {
        "schema_version": 1,
        "task_type": "generic",
        "protocol_id": "WEB-TEST",
        "title": "Web runtime test",
        "protocol_status": "demo",
        "description": "",
        "instructions": "Continue",
        "random_seed": 7,
        "data_directory": "data/experiments",
        "participant_conditions": [],
        "display": {
            "fullscreen": False,
            "background": "#000000",
            "foreground": "#ffffff",
            "font_size": 20,
        },
        "sources": [],
        "blocks": [
            {
                "block_id": "block-1",
                "instructions": "Start block",
                "repetitions": 1,
                "randomize_trials": False,
                "trials": [
                    {
                        "trial_id": "trial-1",
                        "condition": "test",
                        "correct_key": "space",
                        "metadata": {},
                        "phases": [phase],
                    }
                ],
            }
        ],
    }


def wait_for(session, predicate, timeout=3.0, heartbeat=True):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if heartbeat:
            session.heartbeat()
        snapshot = session.snapshot()
        if predicate(snapshot):
            return snapshot
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for session state: {0}".format(snapshot))


def submit_current(session, action, **kwargs):
    """Submit an action for the gate shown by the latest session snapshot."""

    snapshot = session.snapshot()
    kwargs.setdefault("gate_token", snapshot.get("gate_token"))
    return session.submit_action(action, **kwargs)


class WebExperimentSessionTests(unittest.TestCase):
    def test_response_session_completes_and_forces_all_relays_off(self):
        config = ExperimentConfig.from_dict(web_config())
        controller = DemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P001",
                "S1",
                "",
                controller,
                output_directory=output_directory,
            )
            session.start()
            wait_for(session, lambda value: value["screen"] == "instruction")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "block")
            submit_current(session, "continue")
            phase = wait_for(
                session,
                lambda value: value["screen"] == "phase_prepare"
                and value["waiting_for"] == "presentation",
            )
            self.assertEqual(phase["relay_state"], [0, 0, 0, 0])
            session.submit_action(
                "ready",
                client_elapsed_ms=16.7,
                gate_token=phase["gate_token"],
            )
            phase = wait_for(
                session,
                lambda value: value["screen"] == "phase"
                and value["phase"]["presented"],
            )
            session.submit_action(
                "presented",
                client_elapsed_ms=1.2,
                gate_token=phase["gate_token"],
            )
            phase = wait_for(
                session,
                lambda value: value["screen"] == "phase"
                and value["phase"]["started"],
            )
            self.assertEqual(phase["relay_state"], [1, 0, 0, 0])
            session.submit_action(
                "response",
                key="space",
                client_elapsed_ms=12.5,
                gate_token=phase["gate_token"],
            )
            completed = wait_for(
                session,
                lambda value: value["status"] == "completed",
                heartbeat=False,
            )

            self.assertEqual(completed["relay_state"], [0, 0, 0, 0])
            self.assertEqual(controller.last_states, (0, 0, 0, 0))
            self.assertEqual(completed["summary"]["metrics"]["response_count"], 1)
            self.assertEqual(
                completed["summary"]["metrics"]["completed_trial_count"], 1
            )
            self.assertTrue(Path(completed["event_log"]).is_file())
            self.assertTrue(Path(completed["summary_path"]).is_file())

    def test_long_poll_returns_as_soon_as_state_version_advances(self):
        config = ExperimentConfig.from_dict(web_config())
        controller = DemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-LONG-POLL",
                "S1",
                "",
                controller,
                output_directory=output_directory,
            )
            session.start()
            instruction = wait_for(
                session,
                lambda value: value["screen"] == "instruction",
            )
            received = []
            waiter = threading.Thread(
                target=lambda: received.append(
                    session.wait_for_snapshot(instruction["version"], 1.0)
                )
            )
            waiter.start()
            submit_current(session, "continue")
            waiter.join(1.5)

            self.assertFalse(waiter.is_alive())
            self.assertGreater(received[0]["version"], instruction["version"])
            session.request_abort(wait=True)

    def test_late_response_is_rejected_after_timed_window_closes(self):
        config = ExperimentConfig.from_dict(web_config(response_gated=False))
        controller = DemoRelayController()
        controller.connect()
        phase_end_started = threading.Event()
        release_phase_end = threading.Event()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-LATE",
                "S1",
                "",
                controller,
                output_directory=output_directory,
            )
            original_log_trial_event = session._log_trial_event

            def delayed_log(event, **values):
                if event == "phase_end":
                    phase_end_started.set()
                    release_phase_end.wait(1.0)
                return original_log_trial_event(event, **values)

            session._log_trial_event = delayed_log
            session.start()
            wait_for(session, lambda value: value["screen"] == "instruction")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "block")
            submit_current(session, "continue")
            prepare = wait_for(
                session,
                lambda value: value["screen"] == "phase_prepare",
            )
            session.submit_action("ready", gate_token=prepare["gate_token"])
            visible = wait_for(
                session,
                lambda value: value["screen"] == "phase"
                and value["waiting_for"] == "onset",
            )
            session.submit_action(
                "presented",
                gate_token=visible["gate_token"],
            )
            self.assertTrue(phase_end_started.wait(2.0))
            try:
                with self.assertRaises(WebSessionError):
                    session.submit_action(
                        "response",
                        key="space",
                        gate_token=visible["gate_token"],
                    )
            finally:
                release_phase_end.set()
            completed = wait_for(
                session,
                lambda value: value["status"] == "completed",
                heartbeat=False,
            )
            self.assertEqual(completed["summary"]["metrics"]["response_count"], 0)

    def test_heartbeat_timeout_aborts_and_turns_relay_off(self):
        config = ExperimentConfig.from_dict(web_config())
        controller = DemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P002",
                "S1",
                "",
                controller,
                output_directory=output_directory,
                heartbeat_timeout_seconds=0.05,
            )
            session.start()
            aborted = wait_for(
                session,
                lambda value: value["status"] == "aborted",
                timeout=2.0,
                heartbeat=False,
            )

            self.assertEqual(aborted["relay_state"], [0, 0, 0, 0])
            summary = json.loads(Path(aborted["summary_path"]).read_text(encoding="utf-8"))
            self.assertEqual(summary["details"]["reason"], "browser_heartbeat_timeout")

    def test_missing_presentation_ready_aborts_even_with_heartbeats(self):
        config = ExperimentConfig.from_dict(web_config())
        controller = DemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-PRESENTATION-TIMEOUT",
                "S1",
                "",
                controller,
                output_directory=output_directory,
                presentation_timeout_seconds=0.05,
            )
            session.start()
            wait_for(session, lambda value: value["screen"] == "instruction")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "block")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "phase_prepare")
            aborted = wait_for(
                session,
                lambda value: value["status"] == "aborted",
                timeout=2.0,
                heartbeat=True,
            )
            self.assertEqual(aborted["relay_state"], [0, 0, 0, 0])
            summary = json.loads(
                Path(aborted["summary_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                summary["details"]["reason"],
                "browser_presentation_timeout",
            )

    def test_missing_rendered_onset_aborts_and_turns_relay_off(self):
        config = ExperimentConfig.from_dict(web_config())
        controller = RecordingDemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-ONSET-TIMEOUT",
                "S1",
                "",
                controller,
                output_directory=output_directory,
                presentation_timeout_seconds=0.05,
            )
            session.start()
            wait_for(session, lambda value: value["screen"] == "instruction")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "block")
            submit_current(session, "continue")
            prepare = wait_for(
                session,
                lambda value: value["screen"] == "phase_prepare",
            )
            session.submit_action("ready", gate_token=prepare["gate_token"])
            visible = wait_for(
                session,
                lambda value: value["screen"] == "phase"
                and value["waiting_for"] == "onset",
            )
            self.assertEqual(visible["relay_state"], [1, 0, 0, 0])

            aborted = wait_for(
                session,
                lambda value: value["status"] == "aborted",
                timeout=2.0,
                heartbeat=True,
            )

            self.assertEqual(aborted["relay_state"], [0, 0, 0, 0])
            self.assertEqual(controller.last_states, (0, 0, 0, 0))
            summary = json.loads(
                Path(aborted["summary_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                summary["details"]["reason"],
                "browser_presentation_timeout",
            )

    def test_timed_phase_clock_starts_only_after_presented_ack(self):
        document = web_config(response_gated=False)
        phase_document = document["blocks"][0]["trials"][0]["phases"][0]
        phase_document["duration_ms"] = 30
        phase_document["collect_response"] = False
        phase_document["allowed_keys"] = []
        phase_document["end_on_response"] = False
        document["blocks"][0]["trials"][0]["correct_key"] = None
        config = ExperimentConfig.from_dict(document)
        controller = DemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-DELAYED-ONSET",
                "S1",
                "",
                controller,
                output_directory=output_directory,
            )
            session.start()
            wait_for(session, lambda value: value["screen"] == "instruction")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "block")
            submit_current(session, "continue")
            prepare = wait_for(
                session,
                lambda value: value["screen"] == "phase_prepare",
            )
            session.submit_action("ready", gate_token=prepare["gate_token"])
            visible = wait_for(
                session,
                lambda value: value["screen"] == "phase"
                and value["waiting_for"] == "onset",
            )

            time.sleep(0.06)
            session.heartbeat()
            still_waiting = session.snapshot()
            self.assertEqual(still_waiting["waiting_for"], "onset")
            self.assertIsNone(still_waiting["remaining_ms"])

            acknowledged_at = time.monotonic()
            session.submit_action(
                "presented",
                gate_token=visible["gate_token"],
            )
            completed = wait_for(
                session,
                lambda value: value["status"] == "completed",
                heartbeat=False,
            )
            self.assertGreaterEqual(time.monotonic() - acknowledged_at, 0.02)
            self.assertEqual(completed["relay_state"], [0, 0, 0, 0])

    def test_stale_phase_token_cannot_acknowledge_the_next_phase(self):
        document = web_config(response_gated=False)
        first_phase = document["blocks"][0]["trials"][0]["phases"][0]
        first_phase["collect_response"] = False
        first_phase["allowed_keys"] = []
        first_phase["end_on_response"] = False
        first_phase["duration_ms"] = 15
        document["blocks"][0]["trials"][0]["correct_key"] = None
        second_phase = dict(first_phase)
        second_phase["name"] = "second"
        second_phase["lights"] = ["right"]
        document["blocks"][0]["trials"][0]["phases"].append(second_phase)
        config = ExperimentConfig.from_dict(document)
        controller = RecordingDemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-STALE-TOKEN",
                "S1",
                "",
                controller,
                output_directory=output_directory,
            )
            session.start()
            wait_for(session, lambda value: value["screen"] == "instruction")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "block")
            submit_current(session, "continue")

            first_prepare = wait_for(
                session,
                lambda value: value["screen"] == "phase_prepare"
                and value["phase"]["name"] == "response",
            )
            session.submit_action(
                "ready",
                gate_token=first_prepare["gate_token"],
            )
            first_visible = wait_for(
                session,
                lambda value: value["screen"] == "phase"
                and value["phase"]["name"] == "response",
            )
            session.submit_action(
                "presented",
                gate_token=first_visible["gate_token"],
            )
            second_prepare = wait_for(
                session,
                lambda value: value["screen"] == "phase_prepare"
                and value["phase"]["name"] == "second",
            )

            with self.assertRaises(WebSessionError):
                session.submit_action(
                    "ready",
                    gate_token=first_prepare["gate_token"],
                )
            time.sleep(0.03)
            unchanged = session.snapshot()
            self.assertEqual(unchanged["screen"], "phase_prepare")
            self.assertEqual(unchanged["waiting_for"], "presentation")
            self.assertEqual(unchanged["gate_token"], second_prepare["gate_token"])
            self.assertEqual(unchanged["relay_state"], [0, 0, 0, 0])
            self.assertEqual(controller.last_states, (0, 0, 0, 0))

            session.submit_action(
                "ready",
                gate_token=second_prepare["gate_token"],
            )
            second_visible = wait_for(
                session,
                lambda value: value["screen"] == "phase"
                and value["phase"]["name"] == "second",
            )
            session.submit_action(
                "presented",
                gate_token=second_visible["gate_token"],
            )
            completed = wait_for(
                session,
                lambda value: value["status"] == "completed",
                heartbeat=False,
            )
            self.assertEqual(completed["relay_state"], [0, 0, 0, 0])

    def test_failed_abort_off_is_reported_as_unknown_not_off(self):
        config = ExperimentConfig.from_dict(web_config())
        controller = FaultInjectingDemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-FAILED-OFF",
                "S1",
                "",
                controller,
                output_directory=output_directory,
            )
            session.start()
            wait_for(session, lambda value: value["screen"] == "instruction")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "block")
            submit_current(session, "continue")
            prepare = wait_for(
                session,
                lambda value: value["screen"] == "phase_prepare",
            )
            session.submit_action("ready", gate_token=prepare["gate_token"])
            visible = wait_for(
                session,
                lambda value: value["screen"] == "phase"
                and value["waiting_for"] == "onset",
            )
            self.assertEqual(visible["relay_state"], [1, 0, 0, 0])
            controller.fail_off_error = RuntimeError
            controller.fail_off = True

            session.submit_action("abort")
            aborted = wait_for(
                session,
                lambda value: value["status"] == "aborted",
                heartbeat=False,
            )

            self.assertIsNone(aborted["relay_state"])
            self.assertIn("all-off failure", aborted["error"].lower())
            self.assertIn("tidak dapat diverifikasi", aborted["text"])
            self.assertEqual(controller.last_states, (1, 0, 0, 0))
            controller.fail_off = False
            controller.close()

    def test_abort_acceptance_is_serialized_with_relay_activation(self):
        config = ExperimentConfig.from_dict(web_config())
        controller = BlockingActivationDemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-ABORT-ACTIVATION",
                "S1",
                "",
                controller,
                output_directory=output_directory,
            )
            session.start()
            wait_for(session, lambda value: value["screen"] == "instruction")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "block")
            submit_current(session, "continue")
            prepare = wait_for(
                session,
                lambda value: value["screen"] == "phase_prepare",
            )
            session.submit_action("ready", gate_token=prepare["gate_token"])
            self.assertTrue(controller.activation_started.wait(1.0))

            abort_returned = threading.Event()
            abort_attempted = threading.Event()
            original_submit_action = session.submit_action

            def observed_submit_action(action, *args, **kwargs):
                if action == "abort":
                    abort_attempted.set()
                return original_submit_action(action, *args, **kwargs)

            session.submit_action = observed_submit_action

            def abort_session():
                session.submit_action("abort")
                abort_returned.set()

            abort_worker = threading.Thread(target=abort_session)
            abort_worker.start()
            self.assertTrue(abort_attempted.wait(1.0))
            self.assertFalse(abort_returned.wait(0.05))

            controller.release_activation.set()
            self.assertTrue(abort_returned.wait(1.0))
            history_at_acceptance = len(controller.history)
            aborted = wait_for(
                session,
                lambda value: value["status"] == "aborted",
                heartbeat=False,
            )
            abort_worker.join(1.0)

            self.assertFalse(abort_worker.is_alive())
            self.assertEqual(aborted["relay_state"], [0, 0, 0, 0])
            self.assertTrue(any(any(states) for states in controller.history))
            self.assertTrue(
                all(
                    states == (0, 0, 0, 0)
                    for states in controller.history[history_at_acceptance:]
                )
            )

    def test_abort_before_ready_never_energizes_a_relay(self):
        config = ExperimentConfig.from_dict(web_config())
        controller = RecordingDemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-ABORT-READY",
                "S1",
                "",
                controller,
                output_directory=output_directory,
            )
            session.start()
            wait_for(session, lambda value: value["screen"] == "instruction")
            submit_current(session, "continue")
            wait_for(session, lambda value: value["screen"] == "block")
            submit_current(session, "continue")
            phase = wait_for(
                session,
                lambda value: value["screen"] == "phase_prepare",
            )
            session.submit_action("abort")
            with self.assertRaises(WebSessionError):
                session.submit_action("ready", gate_token=phase["gate_token"])
            wait_for(
                session,
                lambda value: value["status"] == "aborted",
                heartbeat=False,
            )
            self.assertFalse(any(any(state) for state in controller.history))

    def test_full_accelerated_pebt_runs_all_49_trials(self):
        source = json.loads(PEBT_CONFIG.read_text(encoding="utf-8"))
        document = expand_pebt_configuration(source)
        document.pop("generator", None)
        for block in document["blocks"]:
            for trial in block["trials"]:
                for phase in trial["phases"]:
                    if phase.get("duration_ms") is not None:
                        phase["duration_ms"] = 1
        config = ExperimentConfig.from_dict(document)
        controller = DemoRelayController()
        controller.connect()
        with tempfile.TemporaryDirectory() as output_directory:
            session = WebExperimentSession(
                config,
                "P-FULL-WEB",
                "S1",
                "interactive_agent",
                controller,
                output_directory=output_directory,
            )
            session.start()
            handled_gates = set()
            handled_phases = set()
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                session.heartbeat()
                snapshot = session.snapshot()
                if snapshot["status"] == "completed":
                    break
                if snapshot["status"] in ("aborted", "error"):
                    self.fail("Full PEBT stopped early: {0}".format(snapshot))
                if snapshot["screen"] in ("instruction", "block"):
                    signature = (snapshot["screen"], snapshot["version"])
                    if signature not in handled_gates:
                        handled_gates.add(signature)
                        try:
                            session.submit_action(
                                "continue",
                                gate_token=snapshot["gate_token"],
                            )
                        except WebSessionError:
                            # The runtime can consume the prior gate between
                            # snapshot and command; this is the same benign
                            # 409 race handled by the browser client.
                            pass
                elif snapshot["screen"] == "phase_prepare":
                    try:
                        session.submit_action(
                            "ready",
                            gate_token=snapshot["gate_token"],
                        )
                    except WebSessionError:
                        pass
                elif (
                    snapshot["screen"] == "phase"
                    and snapshot["waiting_for"] == "onset"
                ):
                    try:
                        session.submit_action(
                            "presented",
                            gate_token=snapshot["gate_token"],
                        )
                    except WebSessionError:
                        pass
                elif (
                    snapshot["screen"] == "phase"
                    and snapshot["waiting_for"] == "phase"
                    and snapshot.get("phase", {}).get("collect_response")
                    and snapshot["phase"].get("started")
                    and not snapshot["phase"].get("responded")
                ):
                    signature = (
                        snapshot.get("trial", {}).get("trial_index"),
                        snapshot["phase"].get("index"),
                    )
                    if signature not in handled_phases:
                        handled_phases.add(signature)
                        try:
                            session.submit_action(
                                "response",
                                key=snapshot["phase"]["allowed_keys"][0],
                                gate_token=snapshot["gate_token"],
                            )
                        except WebSessionError:
                            pass
                time.sleep(0.001)
            else:
                self.fail("Full PEBT Web runtime did not complete in time.")

            self.assertEqual(snapshot["status"], "completed")
            metrics = snapshot["summary"]["metrics"]
            self.assertEqual(metrics["planned_trial_count"], 49)
            self.assertEqual(metrics["completed_trial_count"], 49)
            self.assertEqual(metrics["response_count"], 48)
            self.assertEqual(controller.last_states, (0, 0, 0, 0))


class LocalWebApplicationTests(unittest.TestCase):
    def setUp(self):
        self.output_directory = tempfile.TemporaryDirectory()
        self.application = LocalWebApplication(
            controller=DemoRelayController(),
            demo_mode=True,
            data_root=Path(self.output_directory.name) / "data",
            user_config_root=Path(self.output_directory.name) / "configs" / "user",
        )

    def tearDown(self):
        self.application.shutdown()
        self.output_directory.cleanup()

    def test_manual_control_is_interlocked_during_experiment(self):
        self.application.connect_relay()
        self.application.apply_manual({"left": True, "front": True})
        self.assertEqual(self.application.controller.last_states, (1, 0, 1, 0))
        self.application.start_experiment(
            {
                "document": web_config(),
                "participant_id": "P003",
                "allow_unvalidated": True,
                "client_id": "client-test-003",
            }
        )
        wait_for(
            self.application.session,
            lambda value: value["screen"] == "instruction",
        )
        self.assertEqual(self.application.controller.last_states, (0, 0, 0, 0))
        with self.assertRaises(ApiError) as context:
            self.application.apply_manual({"left": True})
        self.assertEqual(context.exception.status, 409)
        active = self.application.session.snapshot()
        self.application.experiment_action(
            {
                "action": "abort",
                "session_id": active["session_id"],
                "client_id": "client-test-003",
            }
        )
        wait_for(
            self.application.session,
            lambda value: value["status"] == "aborted",
            heartbeat=False,
        )

    def test_builder_load_expands_generator_without_overwriting_source(self):
        loaded = self.application.load_config(
            "configs/pebt_yamawaki_2023_draft.json",
            builder=True,
        )
        self.assertTrue(loaded["expanded_from_generator"])
        self.assertIsNone(loaded["id"])
        self.assertNotIn("generator", loaded["document"])
        self.assertEqual(loaded["summary"]["trial_count"], 49)

    def test_invalid_builder_document_is_not_written(self):
        document = web_config()
        document["protocol_id"] = ""
        filename = "invalid-should-not-be-written.json"

        with self.assertRaises(ApiError) as context:
            self.application.save_config(document, filename)

        self.assertEqual(context.exception.status, 400)
        self.assertFalse((self.application.user_config_root / filename).exists())

    def test_json_boolean_fields_reject_truthy_strings(self):
        with self.assertRaises(ApiError) as manual_context:
            self.application.apply_manual({"left": "false"})
        self.assertEqual(manual_context.exception.status, 400)

        with self.assertRaises(ApiError) as start_context:
            self.application.start_experiment(
                {
                    "document": web_config(),
                    "participant_id": "P-BOOL",
                    "allow_unvalidated": "false",
                    "client_id": "client-test-bool",
                }
            )
        self.assertEqual(start_context.exception.status, 400)

        with self.assertRaises(ApiError) as save_context:
            self.application.save_config(
                web_config(),
                "bad-boolean.json",
                overwrite="false",
            )
        self.assertEqual(save_context.exception.status, 400)

    def test_concurrent_save_without_overwrite_has_one_winner(self):
        barrier = threading.Barrier(3)
        outcomes = []

        def save_once():
            barrier.wait()
            try:
                result = self.application.save_config(
                    web_config(),
                    "concurrent.json",
                    overwrite=False,
                )
                outcomes.append(("saved", result["id"]))
            except ApiError as exc:
                outcomes.append(("error", exc.status))

        workers = [threading.Thread(target=save_once) for _ in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(2.0)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(sorted(item[0] for item in outcomes), ["error", "saved"])
        self.assertIn(("error", 409), outcomes)
        self.assertFalse(list(self.application.user_config_root.glob("*.tmp")))

    def test_delayed_abort_from_old_client_cannot_abort_new_session(self):
        first = self.application.start_experiment(
            {
                "document": web_config(),
                "participant_id": "P-OLD",
                "allow_unvalidated": True,
                "client_id": "client-old-tab",
            }
        )
        wait_for(
            self.application.session,
            lambda value: value["screen"] == "instruction",
        )
        self.application.experiment_action(
            {
                "action": "abort",
                "session_id": first["session_id"],
                "client_id": "client-old-tab",
            }
        )
        wait_for(
            self.application.session,
            lambda value: value["status"] == "aborted",
            heartbeat=False,
        )

        second = self.application.start_experiment(
            {
                "document": web_config(),
                "participant_id": "P-NEW",
                "allow_unvalidated": True,
                "client_id": "client-new-tab",
            }
        )
        wait_for(
            self.application.session,
            lambda value: value["screen"] == "instruction",
        )

        with self.assertRaises(ApiError) as context:
            self.application.experiment_action(
                {
                    "action": "abort",
                    "session_id": first["session_id"],
                    "client_id": "client-old-tab",
                }
            )
        self.assertEqual(context.exception.status, 409)
        self.assertTrue(self.application.session.is_active)

        self.application.experiment_action(
            {
                "action": "abort",
                "session_id": second["session_id"],
                "client_id": "client-new-tab",
            }
        )
        wait_for(
            self.application.session,
            lambda value: value["status"] == "aborted",
            heartbeat=False,
        )

    def test_readback_failure_is_reported_as_unknown_not_all_off(self):
        controller = FaultInjectingDemoRelayController()
        controller.connect()
        controller.set_states((1, 0, 0, 0))
        controller.fail_readback = True
        application = LocalWebApplication(
            controller=controller,
            demo_mode=True,
            data_root=Path(self.output_directory.name) / "fault-data",
            user_config_root=Path(self.output_directory.name) / "fault-configs",
        )
        try:
            snapshot = application.relay_snapshot()
            self.assertIsNone(snapshot["states"])
            self.assertIn("readback", snapshot["error"].lower())
        finally:
            controller.fail_readback = False
            application.shutdown()

    def test_shutdown_surfaces_failed_all_off_verification(self):
        controller = FaultInjectingDemoRelayController()
        controller.connect()
        controller.set_states((1, 0, 0, 0))
        application = LocalWebApplication(
            controller=controller,
            demo_mode=True,
            data_root=Path(self.output_directory.name) / "shutdown-data",
            user_config_root=Path(self.output_directory.name) / "shutdown-configs",
        )
        controller.fail_off = True

        errors = application.shutdown()

        self.assertTrue(errors)
        self.assertIn("OFF GAGAL", errors[0])
        self.assertEqual(controller.last_states, (1, 0, 0, 0))


class LocalHttpServerTests(unittest.TestCase):
    def setUp(self):
        self.output_directory = tempfile.TemporaryDirectory()
        self.application = LocalWebApplication(
            controller=DemoRelayController(),
            demo_mode=True,
            data_root=Path(self.output_directory.name) / "data",
            user_config_root=Path(self.output_directory.name) / "configs" / "user",
        )
        self.server = create_server(self.application, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:{0}".format(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2.0)
        self.application.shutdown()
        self.output_directory.cleanup()

    def request(self, path, method="GET", body=None, token=None, extra_headers=None):
        data = None
        headers = {"Accept": "application/json"}
        headers.update(extra_headers or {})
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-PEBT-Token"] = token
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        return urllib.request.urlopen(request, timeout=3.0)

    def test_static_shell_system_api_and_control_token(self):
        with self.request("/") as response:
            shell = response.read().decode("utf-8")
            self.assertIn("bento-grid", shell)
            self.assertIn("glass-card", shell)
            self.assertIn("Python backend", shell)
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")

        with self.request("/app.js") as response:
            app_source = response.read().decode("utf-8")
            self.assertIn('./start_gate.mjs', app_source)
            self.assertIn("experimentStartGate.tryEnter()", app_source)

        with self.request("/start_gate.mjs") as response:
            gate_source = response.read().decode("utf-8")
            self.assertIn("createExclusiveGate", gate_source)
            self.assertIn("javascript", response.headers["Content-Type"])

        with self.request("/api/system") as response:
            payload = json.loads(response.read().decode("utf-8"))["data"]
            token = payload["control_token"]
            self.assertEqual(payload["mode"], "demo")

        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/relay/connect", method="POST", body={})
        self.assertEqual(context.exception.code, 403)

        with self.request(
            "/api/relay/connect",
            method="POST",
            body={},
            token=token,
        ) as response:
            connected = json.loads(response.read().decode("utf-8"))["data"]
            self.assertEqual(connected["states"], [0, 0, 0, 0])

    def test_config_and_manual_relay_endpoints(self):
        with self.request("/api/system") as response:
            token = json.loads(response.read().decode("utf-8"))["data"][
                "control_token"
            ]
        with self.request("/api/configs") as response:
            configs = json.loads(response.read().decode("utf-8"))["data"]
            self.assertTrue(any(item["trial_count"] == 49 for item in configs))
        self.request("/api/relay/connect", method="POST", body={}, token=token).close()
        with self.request(
            "/api/relay/apply",
            method="POST",
            body={"sides": {"left": True, "right": False, "front": True}},
            token=token,
        ) as response:
            result = json.loads(response.read().decode("utf-8"))["data"]
            self.assertEqual(result["actual"], [1, 0, 1, 0])
        with self.request(
            "/api/relay/off", method="POST", body={}, token=token
        ) as response:
            result = json.loads(response.read().decode("utf-8"))["data"]
            self.assertEqual(result["states"], [0, 0, 0, 0])

    def test_config_path_traversal_is_rejected(self):
        encoded_parent = "%2e%2e%2fmain.py"
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/config?id=" + encoded_parent)
        self.assertEqual(context.exception.code, 400)

    def test_non_loopback_host_header_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request(
                "/api/system",
                extra_headers={"Host": "malicious.example"},
            )
        self.assertEqual(context.exception.code, 403)

    def test_cross_site_browser_requests_are_rejected(self):
        for headers in (
            {"Sec-Fetch-Site": "cross-site"},
            {"Origin": "https://malicious.example"},
        ):
            with self.assertRaises(urllib.error.HTTPError) as context:
                self.request("/api/relay", extra_headers=headers)
            self.assertEqual(context.exception.code, 403)

    @unittest.skipUnless(socket.has_ipv6, "IPv6 is not available")
    def test_ipv6_loopback_server_uses_ipv6_address_family(self):
        try:
            server = create_server(self.application, host="::1", port=0)
        except OSError as exc:
            self.skipTest("IPv6 loopback cannot bind: {0}".format(exc))
        try:
            self.assertEqual(server.address_family, socket.AF_INET6)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
