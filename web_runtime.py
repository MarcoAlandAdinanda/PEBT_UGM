"""Thread-safe experiment runtime for the local browser interface."""

from __future__ import absolute_import

import copy
import threading
import time
from datetime import datetime, timezone

from experiment import ExperimentLogger
from relay_controller import RelayError


class WebSessionError(RuntimeError):
    """Raised when an experiment session cannot accept an operation."""


class _SessionAborted(Exception):
    pass


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class WebExperimentSession(object):
    """Run one compiled experiment independently of a desktop UI toolkit."""

    TERMINAL_STATUSES = ("completed", "aborted", "error")

    def __init__(
        self,
        config,
        participant_id,
        session_label,
        participant_condition,
        controller,
        relay_lock=None,
        output_directory=None,
        heartbeat_timeout_seconds=15.0,
        presentation_timeout_seconds=5.0,
        client_id=None,
    ):
        self.config = config
        self.participant_id = participant_id.strip()
        self.session_label = session_label.strip()
        self.participant_condition = participant_condition.strip().lower()
        self.client_id = str(client_id or "")
        self.controller = controller
        self.relay_lock = relay_lock or threading.RLock()
        self.compiled_trials = config.compile_trials(self.participant_id)
        self.logger = ExperimentLogger(
            config,
            self.participant_id,
            session_label=self.session_label,
            participant_condition=self.participant_condition,
            output_directory=output_directory,
            compiled_trials=self.compiled_trials,
        )
        self.result_path = self.logger.path
        self.summary_path = self.logger.summary_path

        self._condition = threading.Condition(threading.RLock())
        self._thread = None
        self._abort_requested = False
        self._abort_reason = "operator_request"
        self._continue_requested = False
        self._presentation_requested = False
        self._gate_sequence = 0
        self._presentation_received_ns = None
        self._presentation_client_elapsed_ms = None
        self._browser_presented_received_ns = None
        self._browser_presented_client_elapsed_ms = None
        self._active_phase_duration_ms = None
        self._active_phase_collect_response = False
        self._response_window_open = False
        self._pending_response = None
        self._current_compiled_trial = None
        self._phase_index = -1
        self._phase_start_ns = None
        self._phase_deadline_ns = None
        self._scheduled_phase_start_ns = None
        self._trial_response = None
        self._last_block_key = None
        self._version = 0
        self._heartbeat_timeout_ns = int(
            float(heartbeat_timeout_seconds) * 1000000000
        )
        self._presentation_timeout_ns = int(
            float(presentation_timeout_seconds) * 1000000000
        )
        self._last_heartbeat_ns = time.perf_counter_ns()
        self._state = {
            "session_id": self.logger.session_id,
            "status": "starting",
            "screen": "preparing",
            "waiting_for": None,
            "gate_token": None,
            "title": config.title,
            "text": "Menyiapkan eksperimen…",
            "hint": "",
            "progress": {"current": 0, "total": len(self.compiled_trials)},
            "display": self._display_payload(),
            "task_type": config.task_type,
            "protocol_id": config.protocol_id,
            "protocol_status": config.protocol_status,
            "participant_id": self.participant_id,
            "participant_condition": self.participant_condition,
            "phase": None,
            "trial": None,
            "relay_state": [0, 0, 0, 0],
            "summary": None,
            "event_log": str(self.result_path),
            "summary_path": str(self.summary_path),
            "error": None,
            "started_at_utc": _utc_now(),
            "updated_at_utc": _utc_now(),
        }

    @property
    def is_active(self):
        with self._condition:
            return self._state["status"] in ("starting", "running")

    @property
    def is_terminal(self):
        with self._condition:
            return self._state["status"] in self.TERMINAL_STATUSES

    def _display_payload(self, phase=None):
        return {
            "fullscreen": bool(self.config.display.fullscreen),
            "background": (
                phase.background
                if phase is not None and phase.background
                else self.config.display.background
            ),
            "foreground": (
                phase.foreground
                if phase is not None and phase.foreground
                else self.config.display.foreground
            ),
            "font_size": (
                phase.font_size
                if phase is not None and phase.font_size
                else self.config.display.font_size
            ),
        }

    def _contextualize_text(self, value):
        return value.replace(
            "{participant_condition}",
            self.participant_condition or "tidak ditentukan",
        )

    def _publish(self, **changes):
        with self._condition:
            self._publish_locked(**changes)

    def _publish_locked(self, **changes):
        """Publish state while ``self._condition`` is already held."""

        self._state.update(changes)
        self._state["updated_at_utc"] = _utc_now()
        self._version += 1
        self._condition.notify_all()

    def _new_gate_token(self, gate_kind):
        with self._condition:
            self._gate_sequence += 1
            return "{0}:{1}:{2}".format(
                self.logger.session_id,
                self._gate_sequence,
                gate_kind,
            )

    def snapshot(self):
        with self._condition:
            payload = copy.deepcopy(self._state)
            payload["version"] = self._version
            if self._phase_deadline_ns is not None and payload["status"] == "running":
                payload["remaining_ms"] = max(
                    0,
                    round(
                        (self._phase_deadline_ns - time.perf_counter_ns())
                        / 1000000.0
                    ),
                )
            else:
                payload["remaining_ms"] = None
            return payload

    def wait_for_snapshot(self, after_version, timeout_seconds=10.0):
        """Wait until the published state advances, then return a snapshot."""

        after_version = int(after_version)
        timeout_seconds = max(0.0, min(15.0, float(timeout_seconds)))
        with self._condition:
            if self._version <= after_version and not self.is_terminal:
                self._condition.wait_for(
                    lambda: self._version > after_version or self.is_terminal,
                    timeout=timeout_seconds,
                )
        return self.snapshot()

    def start(self):
        with self._condition:
            if self._thread is not None:
                raise WebSessionError("Experiment session has already started.")
            self._thread = threading.Thread(
                target=self._run,
                name="pebt-web-experiment",
                daemon=True,
            )
            self._thread.start()
        return self.snapshot()

    def submit_action(
        self,
        action,
        key=None,
        client_elapsed_ms=None,
        gate_token=None,
    ):
        action = str(action or "").strip().lower()
        normalized_key = str(key or "").strip().lower()
        with self._condition:
            self._last_heartbeat_ns = time.perf_counter_ns()
            status = self._state["status"]
            waiting_for = self._state.get("waiting_for")
            if action == "abort":
                if status not in ("starting", "running"):
                    raise WebSessionError("No running experiment can be aborted.")
                self._abort_requested = True
                self._abort_reason = "operator_request"
                self._condition.notify_all()
                return self.snapshot()

            if status not in ("starting", "running"):
                raise WebSessionError("The experiment is not accepting input.")

            expected_gate_token = self._state.get("gate_token")
            if (
                not expected_gate_token
                or str(gate_token or "") != expected_gate_token
            ):
                raise WebSessionError(
                    "This action belongs to an expired experiment screen."
                )

            if action == "ready":
                if waiting_for != "presentation":
                    raise WebSessionError(
                        "The current phase is not waiting for presentation."
                    )
                if self._abort_requested:
                    raise WebSessionError("The experiment is being aborted.")
                if self._presentation_requested:
                    return self.snapshot()
                self._presentation_requested = True
                self._presentation_received_ns = time.perf_counter_ns()
                self._presentation_client_elapsed_ms = client_elapsed_ms
                self._publish_locked(waiting_for="activation")
                return self.snapshot()

            if action == "presented":
                if waiting_for != "onset" or self._state.get("screen") != "phase":
                    raise WebSessionError("There is no live phase to acknowledge.")
                if self._browser_presented_received_ns is not None:
                    return self.snapshot()
                now_ns = time.perf_counter_ns()
                self._browser_presented_received_ns = now_ns
                self._browser_presented_client_elapsed_ms = client_elapsed_ms
                self._phase_start_ns = now_ns
                self._phase_deadline_ns = (
                    None
                    if self._active_phase_duration_ms is None
                    else now_ns + self._active_phase_duration_ms * 1000000
                )
                self._response_window_open = bool(
                    self._active_phase_collect_response
                )
                if self._state.get("phase"):
                    self._state["phase"]["browser_presented"] = True
                    self._state["phase"]["started"] = True
                self._publish_locked(waiting_for="phase")
                return self.snapshot()

            if action == "continue":
                if waiting_for not in ("instruction_page", "block_start"):
                    raise WebSessionError("Continue is not available on this screen.")
                self._continue_requested = True
                self._publish_locked(waiting_for="advancing")
                return self.snapshot()

            if action != "response":
                raise WebSessionError("Unknown experiment action: {0}.".format(action))
            if waiting_for != "phase" or not self._response_window_open:
                raise WebSessionError("This screen is not collecting a response.")
            phase_payload = self._state.get("phase") or {}
            if not phase_payload.get("collect_response"):
                raise WebSessionError("The current phase does not collect responses.")
            allowed_keys = tuple(phase_payload.get("allowed_keys") or ())
            if normalized_key not in allowed_keys:
                raise WebSessionError(
                    "Response must be one of: {0}.".format(
                        ", ".join(allowed_keys)
                    )
                )
            if self._pending_response is not None or phase_payload.get("responded"):
                raise WebSessionError("A response has already been recorded.")
            now_ns = time.perf_counter_ns()
            if self._phase_deadline_ns is not None and now_ns >= self._phase_deadline_ns:
                self._response_window_open = False
                raise WebSessionError("The response window has already ended.")
            self._pending_response = {
                "key": normalized_key,
                "received_ns": now_ns,
                "client_elapsed_ms": client_elapsed_ms,
            }
            self._response_window_open = False
            if self._state.get("phase"):
                self._state["phase"]["responded"] = True
                self._state["phase"]["response_key"] = normalized_key
            self._publish_locked()
            return self.snapshot()

    def request_abort(self, wait=False, timeout=3.0):
        with self._condition:
            if self._state["status"] in ("starting", "running"):
                self._abort_requested = True
                self._abort_reason = "server_shutdown"
                self._condition.notify_all()
            thread = self._thread
        if wait and thread is not None:
            thread.join(timeout)
        return self.snapshot()

    def _raise_if_aborted(self):
        if (
            not self._abort_requested
            and self._heartbeat_timeout_ns > 0
            and time.perf_counter_ns() - self._last_heartbeat_ns
            > self._heartbeat_timeout_ns
        ):
            self._abort_requested = True
            self._abort_reason = "browser_heartbeat_timeout"
        if self._abort_requested:
            raise _SessionAborted()

    def heartbeat(self):
        with self._condition:
            if self._state["status"] in ("starting", "running"):
                self._last_heartbeat_ns = time.perf_counter_ns()
                self._condition.notify_all()
        return self.snapshot()

    def _wait_for_continue(self, waiting_for):
        with self._condition:
            while not self._continue_requested:
                self._raise_if_aborted()
                self._condition.wait(1.0)
            self._continue_requested = False
        self._publish(waiting_for=None, gate_token=None)

    def _wait_for_presentation(self):
        deadline_ns = time.perf_counter_ns() + self._presentation_timeout_ns
        with self._condition:
            while not self._presentation_requested:
                self._raise_if_aborted()
                remaining_seconds = (
                    deadline_ns - time.perf_counter_ns()
                ) / 1000000000.0
                if remaining_seconds <= 0:
                    self._abort_requested = True
                    self._abort_reason = "browser_presentation_timeout"
                    raise _SessionAborted()
                self._condition.wait(min(1.0, remaining_seconds))
            self._raise_if_aborted()
            self._presentation_requested = False

    def _wait_for_browser_onset(self):
        deadline_ns = time.perf_counter_ns() + self._presentation_timeout_ns
        with self._condition:
            while self._browser_presented_received_ns is None:
                self._raise_if_aborted()
                remaining_seconds = (
                    deadline_ns - time.perf_counter_ns()
                ) / 1000000000.0
                if remaining_seconds <= 0:
                    self._abort_requested = True
                    self._abort_reason = "browser_presentation_timeout"
                    raise _SessionAborted()
                self._condition.wait(min(1.0, remaining_seconds))
            self._raise_if_aborted()

    def _set_relay(self, requested_state):
        requested_state = tuple(requested_state)
        with self.relay_lock:
            self.controller.set_states(requested_state)
            actual_state = tuple(self.controller.get_states())
        if actual_state != requested_state:
            raise RelayError(
                "Relay readback mismatch: requested {0}, received {1}.".format(
                    requested_state, actual_state
                )
            )
        return actual_state

    def _set_all_off(self):
        return self._set_relay((0, 0, 0, 0))

    def _log_trial_event(self, event, **values):
        current = self._current_compiled_trial
        phase = None
        if current is not None and 0 <= self._phase_index < len(current.trial.phases):
            phase = current.trial.phases[self._phase_index]
        base_values = {
            "block_index": current.block_index if current else None,
            "block_id": current.block_id if current else None,
            "repetition": current.repetition if current else None,
            "trial_index": current.trial_index if current else None,
            "trial_id": current.trial.trial_id if current else None,
            "condition": current.trial.condition if current else None,
            "phase_index": self._phase_index if phase else None,
            "phase_name": phase.name if phase else None,
        }
        base_values.update(values)
        self.logger.log(event, **base_values)

    def _run_instruction_pages(self):
        pages = self.config.instruction_pages
        for page_index, page in enumerate(pages):
            self._raise_if_aborted()
            with self._condition:
                self._continue_requested = False
            gate_token = self._new_gate_token("instruction")
            started_ns = time.perf_counter_ns()
            rendered_text = self._contextualize_text(page.text)
            self.logger.log(
                "instruction_page_start",
                details={
                    "page_index": page_index + 1,
                    "page_count": len(pages),
                    "page_id": page.page_id,
                    "title": page.title,
                    "text": rendered_text,
                },
            )
            self._publish(
                status="running",
                screen="instruction",
                waiting_for="instruction_page",
                gate_token=gate_token,
                title=page.title,
                text=rendered_text,
                hint=page.hint,
                display=self._display_payload(),
                instruction={
                    "index": page_index + 1,
                    "count": len(pages),
                    "page_id": page.page_id,
                },
                phase=None,
                trial=None,
            )
            self._wait_for_continue("instruction_page")
            elapsed_ms = round(
                (time.perf_counter_ns() - started_ns) / 1000000.0, 3
            )
            self.logger.log(
                "instruction_page_complete",
                elapsed_ms=elapsed_ms,
                details={
                    "page_index": page_index + 1,
                    "page_count": len(pages),
                    "page_id": page.page_id,
                    "title": page.title,
                },
            )

    def _run_block_gate(self, current):
        with self._condition:
            self._continue_requested = False
        gate_token = self._new_gate_token("block")
        started_ns = time.perf_counter_ns()
        instructions = self._contextualize_text(current.block_instructions)
        self.logger.log(
            "block_start",
            block_index=current.block_index,
            block_id=current.block_id,
            repetition=current.repetition,
            details={"instructions": instructions},
        )
        self._publish(
            status="running",
            screen="block",
            waiting_for="block_start",
            gate_token=gate_token,
            title="Block {0}".format(current.block_id),
            text=instructions,
            hint="Tekan SPASI atau tombol lanjut untuk memulai blok",
            display=self._display_payload(),
            block={
                "block_index": current.block_index,
                "block_id": current.block_id,
                "repetition": current.repetition,
            },
            phase=None,
            trial=None,
        )
        self._wait_for_continue("block_start")
        elapsed_ms = round(
            (time.perf_counter_ns() - started_ns) / 1000000.0, 3
        )
        self.logger.log(
            "block_gate_complete",
            block_index=current.block_index,
            block_id=current.block_id,
            repetition=current.repetition,
            elapsed_ms=elapsed_ms,
            details={"instructions": instructions},
        )

    def _record_pending_response(self, phase):
        with self._condition:
            pending = self._pending_response
            self._pending_response = None
        if pending is None:
            return None
        key_name = pending["key"]
        response_time_ms = round(
            (pending["received_ns"] - self._phase_start_ns) / 1000000.0, 3
        )
        correct = (
            None
            if self._current_compiled_trial.trial.correct_key is None
            else key_name == self._current_compiled_trial.trial.correct_key
        )
        response = {
            "key": key_name,
            "response_time_ms": response_time_ms,
            "correct": correct,
        }
        self._trial_response = dict(response)
        response_details = (
            self._current_compiled_trial.trial.metadata
            .get("response_details", {})
            .get(key_name, {})
        )
        details = dict(response_details)
        if pending.get("client_elapsed_ms") is not None:
            details["client_elapsed_ms"] = pending["client_elapsed_ms"]
        self._log_trial_event(
            "response",
            response_key=key_name,
            response_time_ms=response_time_ms,
            correct=correct,
            details=details,
        )
        return response

    def _wait_for_phase_end(self, phase):
        response = None
        termination_reason = "timer"
        with self._condition:
            while True:
                self._raise_if_aborted()
                if self._pending_response is not None:
                    break
                if self._phase_deadline_ns is None:
                    self._condition.wait(1.0)
                    continue
                remaining_seconds = (
                    self._phase_deadline_ns - time.perf_counter_ns()
                ) / 1000000000.0
                if remaining_seconds <= 0:
                    self._response_window_open = False
                    return response, termination_reason
                self._condition.wait(min(remaining_seconds, 1.0))

        response = self._record_pending_response(phase)
        if response is not None and phase.end_on_response:
            return response, "response"

        if self._phase_deadline_ns is None:
            while True:
                self._raise_if_aborted()
                if response is not None:
                    return response, "response"
                with self._condition:
                    self._condition.wait(1.0)

        while True:
            self._raise_if_aborted()
            remaining_seconds = (
                self._phase_deadline_ns - time.perf_counter_ns()
            ) / 1000000000.0
            if remaining_seconds <= 0:
                return response, "timer"
            with self._condition:
                self._condition.wait(min(remaining_seconds, 1.0))

    def _run_phase(self, phase):
        requested_state = phase.relay_states
        with self._condition:
            self._phase_start_ns = None
            self._phase_deadline_ns = None
            self._pending_response = None
            self._response_window_open = False
            self._presentation_requested = False
            self._presentation_received_ns = None
            self._presentation_client_elapsed_ms = None
            self._browser_presented_received_ns = None
            self._browser_presented_client_elapsed_ms = None
            self._active_phase_duration_ms = phase.duration_ms
            self._active_phase_collect_response = bool(phase.collect_response)
        gate_token = self._new_gate_token("phase")
        current = self._current_compiled_trial
        trial_metadata = dict(current.trial.metadata)
        phase_payload = {
            "index": self._phase_index,
            "name": phase.name,
            "duration_ms": phase.duration_ms,
            "lights": list(phase.lights),
            "collect_response": bool(phase.collect_response),
            "allowed_keys": list(phase.allowed_keys),
            "end_on_response": bool(phase.end_on_response),
            "responded": False,
            "presented": False,
            "browser_presented": False,
            "started": False,
        }
        self._publish(
            status="running",
            screen="phase_prepare",
            waiting_for="presentation",
            gate_token=gate_token,
            title=self.config.title,
            text="",
            hint="Menyiapkan onset stimulus…",
            display=self._display_payload(phase),
            progress={
                "current": current.trial_index,
                "total": len(self.compiled_trials),
            },
            trial={
                "trial_index": current.trial_index,
                "trial_id": current.trial.trial_id,
                "condition": current.trial.condition,
                "block_id": current.block_id,
                "metadata": trial_metadata,
            },
            phase=dict(phase_payload),
        )
        self._wait_for_presentation()

        # Abort acceptance and relay activation share the condition lock. If
        # abort wins, no output is energized; if activation wins, abort is not
        # accepted until the command/readback and visible state are published.
        with self._condition:
            self._raise_if_aborted()
            command_started_ns = time.perf_counter_ns()
            actual_state = self._set_relay(requested_state)
            command_finished_ns = time.perf_counter_ns()
            phase_payload["presented"] = True
            self._publish_locked(
                screen="phase",
                waiting_for="onset",
                text=self._contextualize_text(phase.text),
                hint=(
                    "Gunakan tombol respons yang tersedia"
                    if phase.collect_response
                    else ""
                ),
                phase=dict(phase_payload),
                relay_state=list(actual_state),
            )
        self._wait_for_browser_onset()
        self._raise_if_aborted()

        drift_ms = None
        if self._scheduled_phase_start_ns is not None:
            drift_ms = round(
                (self._phase_start_ns - self._scheduled_phase_start_ns)
                / 1000000.0,
                3,
            )
        self._log_trial_event(
            "phase_start",
            scheduled_duration_ms=phase.duration_ms,
            drift_ms=drift_ms,
            lights=phase.lights,
            relay_state=actual_state,
            details={
                "command_duration_ms": round(
                    (command_finished_ns - command_started_ns) / 1000000.0, 3
                ),
                "browser_ready_to_relay_ms": (
                    None
                    if self._presentation_received_ns is None
                    else round(
                        (command_started_ns - self._presentation_received_ns)
                        / 1000000.0,
                        3,
                    )
                ),
                "browser_ready_client_elapsed_ms": self._presentation_client_elapsed_ms,
                "relay_to_browser_presented_ms": round(
                    (self._browser_presented_received_ns - command_finished_ns)
                    / 1000000.0,
                    3,
                ),
                "browser_presentation_client_elapsed_ms": (
                    self._browser_presented_client_elapsed_ms
                ),
                "requested_relay_state": requested_state,
                "allowed_keys": phase.allowed_keys,
                "collect_response": phase.collect_response,
                "end_on_response": phase.end_on_response,
                "run_if_response_key": phase.run_if_response_key,
                "runtime": "local_web_backend",
            },
        )

        response, termination_reason = self._wait_for_phase_end(phase)
        phase_end_ns = time.perf_counter_ns()
        with self._condition:
            self._response_window_open = False
        boundary_state = self._set_all_off()
        self._publish(
            screen="phase_transition",
            waiting_for=None,
            gate_token=None,
            text="",
            hint="",
            phase=None,
            relay_state=list(boundary_state),
        )
        elapsed_ms = round(
            (phase_end_ns - self._phase_start_ns) / 1000000.0, 3
        )
        end_drift_ms = None
        if phase.duration_ms is not None and termination_reason == "timer":
            end_drift_ms = round(elapsed_ms - phase.duration_ms, 3)
        response = response or {}
        self._log_trial_event(
            "phase_end",
            scheduled_duration_ms=phase.duration_ms,
            elapsed_ms=elapsed_ms,
            drift_ms=end_drift_ms,
            lights=phase.lights,
            relay_state=phase.relay_states,
            response_key=response.get("key"),
            response_time_ms=response.get("response_time_ms"),
            correct=response.get("correct"),
            details={
                "termination_reason": termination_reason,
                "browser_presentation_delay_ms": (
                    None
                    if self._browser_presented_received_ns is None
                    else round(
                        (self._browser_presented_received_ns - command_finished_ns)
                        / 1000000.0,
                        3,
                    )
                ),
                "browser_presentation_client_elapsed_ms": (
                    self._browser_presented_client_elapsed_ms
                ),
                "phase_boundary_relay_state": boundary_state,
            },
        )
        if phase.collect_response and not response and termination_reason == "timer":
            self._log_trial_event("response_timeout")
        if termination_reason == "response" or phase.duration_ms is None:
            self._scheduled_phase_start_ns = time.perf_counter_ns()
        else:
            self._scheduled_phase_start_ns = self._phase_deadline_ns
        self._phase_deadline_ns = None

    def _run_trial(self, current):
        self._current_compiled_trial = current
        self._phase_index = -1
        self._trial_response = None
        self._scheduled_phase_start_ns = time.perf_counter_ns()
        self._log_trial_event("trial_start", details=dict(current.trial.metadata))
        for phase_index, phase in enumerate(current.trial.phases):
            self._raise_if_aborted()
            self._phase_index = phase_index
            selected_key = (
                self._trial_response.get("key") if self._trial_response else None
            )
            if (
                phase.run_if_response_key is not None
                and phase.run_if_response_key != selected_key
            ):
                self._log_trial_event(
                    "phase_skipped",
                    details={
                        "run_if_response_key": phase.run_if_response_key,
                        "selected_response_key": selected_key,
                    },
                )
                continue
            self._run_phase(phase)
        actual_state = self._set_all_off()
        self._log_trial_event("trial_end", relay_state=actual_state)
        self._publish(relay_state=list(actual_state))

    def _completion_payload(self):
        summary = self.logger.summary
        return {
            "metrics": summary,
            "event_log": str(self.result_path),
            "summary_path": str(self.summary_path),
        }

    def _run(self):
        try:
            initial_state = self._set_all_off()
            self.logger.log(
                "session_start",
                relay_state=initial_state,
                details={
                    "title": self.config.title,
                    "task_type": self.config.task_type,
                    "participant_condition": self.participant_condition,
                    "trial_count": self.config.trial_count,
                    "estimated_duration_ms": self.config.estimated_duration_ms,
                    "duration_bounds_ms": self.config.duration_bounds_ms,
                    "runtime": "local_web_backend",
                    "sources": [
                        {
                            "source_type": source.source_type,
                            "title": source.title,
                            "citation": source.citation,
                            "pages": source.pages,
                        }
                        for source in self.config.sources
                    ],
                },
            )
            self._publish(status="running", relay_state=list(initial_state))
            self._run_instruction_pages()
            for current in self.compiled_trials:
                self._raise_if_aborted()
                block_key = (current.block_index, current.repetition)
                if block_key != self._last_block_key:
                    self._last_block_key = block_key
                    self._run_block_gate(current)
                self._run_trial(current)
            actual_state = self._set_all_off()
            self.logger.log("session_complete", relay_state=actual_state)
            self.logger.finalize("completed")
            completion = self._completion_payload()
            self._publish(
                status="completed",
                screen="complete",
                waiting_for=None,
                gate_token=None,
                title="Eksperimen selesai",
                text="Seluruh trial telah diselesaikan dan data sudah disimpan.",
                hint="Kembali ke dashboard untuk meninjau ringkasan.",
                phase=None,
                relay_state=list(actual_state),
                summary=completion,
            )
        except _SessionAborted:
            details = {"reason": self._abort_reason}
            try:
                actual_state = self._set_all_off()
            except Exception as shutdown_error:
                actual_state = None
                details["shutdown_error"] = str(shutdown_error)
            self.logger.log(
                "session_aborted",
                relay_state=actual_state,
                details=details or None,
            )
            self.logger.finalize("aborted", details=details)
            safety_failure = details.get("shutdown_error")
            self._publish(
                status="aborted",
                screen="aborted",
                waiting_for=None,
                gate_token=None,
                title="Eksperimen dibatalkan",
                text=(
                    "Data parsial telah disimpan. Status relay tidak dapat "
                    "diverifikasi; putuskan daya beban dan periksa perangkat."
                    if safety_failure
                    else "Data parsial telah disimpan."
                ),
                hint=(
                    "PERINGATAN KESELAMATAN: perintah OFF gagal."
                    if safety_failure
                    else ""
                ),
                phase=None,
                relay_state=(
                    None if actual_state is None else list(actual_state)
                ),
                error=safety_failure,
                summary=self._completion_payload(),
            )
        except Exception as exc:
            details = {"error": str(exc)}
            try:
                actual_state = self._set_all_off()
            except Exception as shutdown_error:
                actual_state = None
                details["shutdown_error"] = str(shutdown_error)
            try:
                self.logger.log("session_error", details=details)
                self.logger.finalize("error", details=details)
            finally:
                safety_failure = details.get("shutdown_error")
                self._publish(
                    status="error",
                    screen="error",
                    waiting_for=None,
                    gate_token=None,
                    title="Eksperimen dihentikan",
                    text="Terjadi error pada runtime eksperimen.",
                    hint=(
                        "PERINGATAN KESELAMATAN: status relay tidak diketahui; "
                        "putuskan daya beban."
                        if safety_failure
                        else "Periksa detail error dan event log."
                    ),
                    phase=None,
                    relay_state=(
                        None if actual_state is None else list(actual_state)
                    ),
                    error=(
                        "{0}; fail-safe OFF gagal: {1}".format(
                            exc,
                            safety_failure,
                        )
                        if safety_failure
                        else str(exc)
                    ),
                    summary=self._completion_payload(),
                )
        finally:
            self._phase_deadline_ns = None
            self.logger.close()
