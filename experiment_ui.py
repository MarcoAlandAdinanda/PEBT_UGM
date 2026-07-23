"""Tkinter setup panel and timed runner for configurable experiments."""

from __future__ import absolute_import

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from experiment import ConfigurationError, ExperimentConfig, ExperimentLogger
from relay_controller import RelayError


PANEL_COLORS = {
    "background": "#F3F6FA",
    "surface": "#FFFFFF",
    "navy": "#17324D",
    "muted": "#62748A",
    "line": "#D7E0EA",
    "green": "#25835B",
    "warning": "#A56700",
    "warning_background": "#FFF4D6",
    "danger": "#B64242",
}


def _normalize_key(keysym):
    key_name = keysym.lower()
    aliases = {
        "return": "enter",
        "kp_enter": "enter",
        "escape": "escape",
    }
    return aliases.get(key_name, key_name)


class PebtStimulusCanvas(tk.Canvas):
    """Draw the paper's PEBT choice/wait structure without external assets."""

    def __init__(self, master):
        tk.Canvas.__init__(self, master, highlightthickness=0, bd=0)
        self._metadata = None
        self._phase_name = None
        self._background = "#F7F7F7"
        self._foreground = "#111111"
        self.bind("<Configure>", self._redraw)

    def present(self, metadata, phase_name, background, foreground):
        self._metadata = dict(metadata or {})
        self._phase_name = phase_name
        self._background = background
        self._foreground = foreground
        self.configure(bg=background)
        self._redraw()

    def _redraw(self, event=None):
        if self._metadata is None:
            return
        self.delete("all")
        width = max(self.winfo_width(), 900)
        height = max(self.winfo_height(), 520)
        if self._phase_name == "choice":
            self._draw_choice(width, height)
        else:
            self._draw_wait(width, height)

    def _draw_bulbs(self, center_x, start_y, active_count):
        spacing_x = 42
        spacing_y = 48
        start_x = center_x - (spacing_x * 1.5)
        for index in range(12):
            column = index % 4
            row = index // 4
            x_coord = start_x + (column * spacing_x)
            y_coord = start_y + (row * spacing_y)
            active = index < active_count
            fill = "#F5C542" if active else "#E2E7ED"
            outline = "#B17D00" if active else "#9AA7B5"
            self.create_oval(
                x_coord - 12,
                y_coord - 15,
                x_coord + 12,
                y_coord + 10,
                fill=fill,
                outline=outline,
                width=2,
            )
            self.create_rectangle(
                x_coord - 5,
                y_coord + 9,
                x_coord + 5,
                y_coord + 16,
                fill="#708094",
                outline="",
            )

    def _draw_option_card(
        self,
        left,
        top,
        right,
        bottom,
        title,
        wait_seconds,
        active_lights,
        emissions,
        key_label,
        accent,
    ):
        self.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill="#FFFFFF",
            outline=accent,
            width=3,
        )
        center_x = (left + right) / 2
        self.create_text(
            center_x,
            top + 40,
            text=title,
            fill=accent,
            font=("Segoe UI Semibold", 24),
        )
        self.create_text(
            center_x,
            top + 83,
            text="Waktu perjalanan: {0} detik".format(wait_seconds),
            fill=self._foreground,
            font=("Segoe UI", 15),
        )
        self._draw_bulbs(center_x, top + 145, active_lights)
        self.create_text(
            center_x,
            top + 292,
            text="Lampu: {0} dari 12\nEmisi CO2: {1} L/jam".format(
                active_lights, emissions
            ),
            fill=self._foreground,
            font=("Segoe UI", 14),
            justify="center",
        )
        self.create_rectangle(
            center_x - 92,
            bottom - 58,
            center_x + 92,
            bottom - 18,
            fill=accent,
            outline="",
        )
        self.create_text(
            center_x,
            bottom - 38,
            text=key_label,
            fill="#FFFFFF",
            font=("Segoe UI Semibold", 13),
        )

    def _draw_choice(self, width, height):
        metadata = self._metadata
        self.create_text(
            width / 2,
            35,
            text="Moda perjalanan mana yang Anda pilih?",
            fill=self._foreground,
            font=("Segoe UI Semibold", 22),
        )
        margin = max(35, width * 0.055)
        gap = max(105, width * 0.13)
        card_width = (width - (2 * margin) - gap) / 2
        top = 70
        bottom = min(height - 78, 500)
        left_card = (margin, top, margin + card_width, bottom)
        right_card = (width - margin - card_width, top, width - margin, bottom)
        self._draw_option_card(
            *left_card,
            title="SEST",
            wait_seconds=metadata.get("sest_wait_seconds", "-"),
            active_lights=0,
            emissions=0,
            key_label="PANAH KIRI",
            accent="#25725B",
        )
        light_count = int(metadata.get("light_count", 0))
        self._draw_option_card(
            *right_card,
            title="DIFT",
            wait_seconds=metadata.get("dift_wait_seconds", "-"),
            active_lights=light_count,
            emissions=metadata.get("co2_liters_per_hour_dift", 0),
            key_label="PANAH KANAN",
            accent="#9A6200",
        )
        self.create_text(
            width / 2,
            190,
            text="Selisih\n{0} detik".format(
                metadata.get("time_difference_seconds", "-")
            ),
            fill=self._foreground,
            font=("Segoe UI Semibold", 14),
            justify="center",
        )
        self.create_text(
            width / 2,
            height - 42,
            text="Observer: {0}".format(
                metadata.get("observer_label", "tidak ditentukan")
            ),
            fill="#52667A",
            font=("Segoe UI", 11),
        )

    def _draw_wait(self, width, height):
        metadata = self._metadata
        if self._phase_name == "lamp_confirmation":
            title = "KONFIRMASI LAMPU"
            subtitle = "12 lampu menyala selama 10 detik"
            active_lights = 12
            emissions = metadata.get("co2_liters_per_hour_dift", 120)
        elif self._phase_name == "dift_wait":
            title = "menunggu..."
            active_lights = int(metadata.get("light_count", 0))
            subtitle = "DIFT dipilih - {0} lampu menyala".format(active_lights)
            emissions = metadata.get("co2_liters_per_hour_dift", 0)
        else:
            title = "menunggu..."
            subtitle = "SEST dipilih - lampu tidak menyala"
            active_lights = 0
            emissions = 0
        self.create_text(
            width / 2,
            85,
            text=title,
            fill=self._foreground,
            font=("Segoe UI Semibold", 30),
        )
        self._draw_bulbs(width / 2, 180, active_lights)
        self.create_text(
            width / 2,
            360,
            text="{0}\nEmisi CO2: {1} L/jam".format(subtitle, emissions),
            fill=self._foreground,
            font=("Segoe UI", 18),
            justify="center",
        )


class ExperimentRunnerWindow(object):
    """Execute a compiled protocol using Tk's event loop and monotonic timing."""

    def __init__(
        self,
        parent,
        config,
        participant_id,
        session_label,
        controller,
        participant_condition="",
        on_finished=None,
        output_directory=None,
    ):
        self.parent = parent
        self.config = config
        self.participant_id = participant_id
        self.session_label = session_label
        self.participant_condition = participant_condition.strip().lower()
        self.controller = controller
        self.on_finished = on_finished
        self.compiled_trials = config.compile_trials(participant_id)
        self.logger = ExperimentLogger(
            config,
            participant_id,
            session_label=session_label,
            participant_condition=self.participant_condition,
            output_directory=output_directory,
            compiled_trials=self.compiled_trials,
        )
        self.result_path = self.logger.path
        self.summary_path = self.logger.summary_path

        self.window = tk.Toplevel(parent)
        self.window.title("Eksperimen - {0}".format(config.title))
        self.window.configure(bg=config.display.background)
        if config.display.fullscreen:
            self.window.attributes("-fullscreen", True)
        else:
            self.window.geometry("1000x680")
            self.window.minsize(800, 560)
        self.window.protocol("WM_DELETE_WINDOW", self.request_abort)
        self.window.bind("<KeyPress>", self._handle_key)

        self.progress_label = tk.Label(
            self.window,
            text="",
            bg=config.display.background,
            fg=config.display.foreground,
            font=("Segoe UI", 11),
            padx=24,
            pady=18,
        )
        self.progress_label.pack(fill="x", side="top")

        self.stimulus_frame = tk.Frame(
            self.window,
            bg=config.display.background,
        )
        self.stimulus_frame.pack(fill="both", expand=True)

        self.display_label = tk.Label(
            self.stimulus_frame,
            text="",
            bg=config.display.background,
            fg=config.display.foreground,
            font=("Segoe UI", config.display.font_size),
            justify="center",
            wraplength=900,
            padx=60,
            pady=40,
        )
        self.display_label.pack(fill="both", expand=True)
        self.pebt_canvas = PebtStimulusCanvas(self.stimulus_frame)

        self.hint_label = tk.Label(
            self.window,
            text="ESC = batalkan eksperimen",
            bg=config.display.background,
            fg=config.display.foreground,
            font=("Segoe UI", 10),
            padx=24,
            pady=16,
        )
        self.hint_label.pack(fill="x", side="bottom")

        self._after_id = None
        self._waiting_for = None
        self._instruction_page_index = -1
        self._instruction_page_started_ns = None
        self._current_trial_offset = -1
        self._current_compiled_trial = None
        self._phase_index = -1
        self._phase_start_ns = None
        self._scheduled_phase_start_ns = None
        self._current_response = None
        self._trial_response = None
        self._last_block_key = None
        self._block_gate_started_ns = None
        self._current_block_instructions_display = ""
        self._closed = False

        self.logger.log(
            "session_start",
            details={
                "title": config.title,
                "task_type": config.task_type,
                "participant_condition": self.participant_condition,
                "trial_count": config.trial_count,
                "estimated_duration_ms": config.estimated_duration_ms,
                "duration_bounds_ms": config.duration_bounds_ms,
                "sources": [
                    {
                        "source_type": source.source_type,
                        "title": source.title,
                        "citation": source.citation,
                        "pages": source.pages,
                    }
                    for source in config.sources
                ],
            },
        )
        self._show_next_instruction_page()
        self.window.grab_set()
        self.window.focus_force()

    def _contextualize_text(self, value):
        return value.replace(
            "{participant_condition}",
            self.participant_condition or "tidak ditentukan",
        )

    def _show_text_display(self, text, background, foreground, font_size):
        self.pebt_canvas.pack_forget()
        if not self.display_label.winfo_manager():
            self.display_label.pack(fill="both", expand=True)
        self.stimulus_frame.configure(bg=background)
        self.display_label.configure(
            text=text,
            bg=background,
            fg=foreground,
            font=("Segoe UI", font_size),
        )

    def _show_gate(self, text, hint):
        self._show_text_display(
            text,
            self.config.display.background,
            self.config.display.foreground,
            self.config.display.font_size,
        )
        self.progress_label.configure(text=self.config.title)
        self.hint_label.configure(text=hint + "  |  ESC = batalkan")

    def _show_next_instruction_page(self):
        self._instruction_page_index += 1
        if self._instruction_page_index >= len(self.config.instruction_pages):
            self._waiting_for = None
            self._begin_next_trial()
            return
        page = self.config.instruction_pages[self._instruction_page_index]
        rendered_text = self._contextualize_text(page.text)
        self._waiting_for = "instruction_page"
        self._instruction_page_started_ns = time.perf_counter_ns()
        self.logger.log(
            "instruction_page_start",
            details={
                "page_index": self._instruction_page_index + 1,
                "page_count": len(self.config.instruction_pages),
                "page_id": page.page_id,
                "title": page.title,
                "text": rendered_text,
            },
        )
        self._show_gate(
            "{0}\n\n{1}".format(page.title, rendered_text),
            page.hint,
        )

    def _handle_key(self, event):
        key_name = _normalize_key(event.keysym)
        if key_name == "escape":
            self.request_abort()
            return "break"

        if self._waiting_for == "instruction_page":
            if key_name == "space":
                page = self.config.instruction_pages[self._instruction_page_index]
                elapsed_ms = round(
                    (time.perf_counter_ns() - self._instruction_page_started_ns)
                    / 1000000.0,
                    3,
                )
                self.logger.log(
                    "instruction_page_complete",
                    elapsed_ms=elapsed_ms,
                    details={
                        "page_index": self._instruction_page_index + 1,
                        "page_count": len(self.config.instruction_pages),
                        "page_id": page.page_id,
                        "title": page.title,
                    },
                )
                self._instruction_page_started_ns = None
                self._show_next_instruction_page()
            return "break"

        if self._waiting_for == "block_start":
            if key_name == "space":
                self._waiting_for = None
                elapsed_ms = None
                if self._block_gate_started_ns is not None:
                    elapsed_ms = round(
                        (time.perf_counter_ns() - self._block_gate_started_ns)
                        / 1000000.0,
                        3,
                    )
                current = self._current_compiled_trial
                self.logger.log(
                    "block_gate_complete",
                    block_index=current.block_index,
                    block_id=current.block_id,
                    repetition=current.repetition,
                    elapsed_ms=elapsed_ms,
                    details={
                        "instructions": self._current_block_instructions_display
                    },
                )
                self._block_gate_started_ns = None
                self._start_current_trial()
            return "break"

        if self._waiting_for == "complete":
            if key_name in ("space", "enter"):
                self._close_window("completed")
            return "break"

        if self._waiting_for != "phase" or self._current_compiled_trial is None:
            return "break"

        phase = self._current_compiled_trial.trial.phases[self._phase_index]
        if (
            phase.collect_response
            and self._current_response is None
            and key_name in phase.allowed_keys
        ):
            response_time_ms = round(
                (time.perf_counter_ns() - self._phase_start_ns) / 1000000.0, 3
            )
            correct = (
                None
                if self._current_compiled_trial.trial.correct_key is None
                else key_name == self._current_compiled_trial.trial.correct_key
            )
            self._current_response = {
                "key": key_name,
                "response_time_ms": response_time_ms,
                "correct": correct,
            }
            self._trial_response = dict(self._current_response)
            response_details = (
                self._current_compiled_trial.trial.metadata
                .get("response_details", {})
                .get(key_name, {})
            )
            self._log_trial_event(
                "response",
                response_key=key_name,
                response_time_ms=response_time_ms,
                correct=correct,
                details=dict(response_details),
            )
            if phase.end_on_response:
                if self._after_id is not None:
                    self.window.after_cancel(self._after_id)
                    self._after_id = None
                self._finish_current_phase(termination_reason="response")
        return "break"

    def _begin_next_trial(self):
        self._current_trial_offset += 1
        if self._current_trial_offset >= len(self.compiled_trials):
            self._complete_experiment()
            return

        self._current_compiled_trial = self.compiled_trials[
            self._current_trial_offset
        ]
        current = self._current_compiled_trial
        block_key = (current.block_index, current.repetition)
        if block_key != self._last_block_key:
            self._last_block_key = block_key
            self._waiting_for = "block_start"
            self._block_gate_started_ns = time.perf_counter_ns()
            self._current_block_instructions_display = self._contextualize_text(
                current.block_instructions
            )
            self.logger.log(
                "block_start",
                block_index=current.block_index,
                block_id=current.block_id,
                repetition=current.repetition,
                details={
                    "instructions": self._current_block_instructions_display
                },
            )
            self._show_gate(
                self._current_block_instructions_display,
                "Tekan SPASI untuk memulai blok",
            )
            return
        self._start_current_trial()

    def _start_current_trial(self):
        self._phase_index = -1
        self._trial_response = None
        self._scheduled_phase_start_ns = time.perf_counter_ns()
        self._log_trial_event(
            "trial_start",
            details=dict(self._current_compiled_trial.trial.metadata),
        )
        self._run_next_phase()

    def _run_next_phase(self):
        trial = self._current_compiled_trial.trial
        while True:
            self._phase_index += 1
            if self._phase_index >= len(trial.phases):
                self._finish_current_trial()
                return
            phase = trial.phases[self._phase_index]
            selected_key = (
                self._trial_response.get("key") if self._trial_response else None
            )
            if (
                phase.run_if_response_key is None
                or phase.run_if_response_key == selected_key
            ):
                break
            self._log_trial_event(
                "phase_skipped",
                details={
                    "run_if_response_key": phase.run_if_response_key,
                    "selected_response_key": selected_key,
                },
            )

        requested_state = phase.relay_states
        command_started_ns = time.perf_counter_ns()
        try:
            self.controller.set_states(requested_state)
            actual_state = self.controller.get_states()
            if tuple(actual_state) != tuple(requested_state):
                raise RelayError(
                    "Relay readback mismatch: requested {0}, received {1}.".format(
                        requested_state, actual_state
                    )
                )
        except RelayError as exc:
            self._fail_experiment(exc)
            return
        command_finished_ns = time.perf_counter_ns()

        background = phase.background or self.config.display.background
        foreground = phase.foreground or self.config.display.foreground
        font_size = phase.font_size or self.config.display.font_size
        self.window.configure(bg=background)
        trial_metadata = self._current_compiled_trial.trial.metadata
        if (
            self.config.task_type == "pebt"
            and trial_metadata.get("trial_role")
            in ("pebt_choice", "lamp_confirmation")
        ):
            self.display_label.pack_forget()
            if not self.pebt_canvas.winfo_manager():
                self.pebt_canvas.pack(fill="both", expand=True)
            self.stimulus_frame.configure(bg=background)
            self.pebt_canvas.present(
                trial_metadata,
                phase.name,
                background,
                foreground,
            )
        else:
            self._show_text_display(
                phase.text,
                background,
                foreground,
                font_size,
            )
        self.progress_label.configure(
            text="Trial {0}/{1}".format(
                self._current_compiled_trial.trial_index,
                len(self.compiled_trials),
            ),
            bg=background,
            fg=foreground,
        )
        self.hint_label.configure(bg=background, fg=foreground)
        self.window.update_idletasks()

        self._phase_start_ns = time.perf_counter_ns()
        drift_ms = None
        if self._scheduled_phase_start_ns is not None:
            drift_ms = round(
                (self._phase_start_ns - self._scheduled_phase_start_ns)
                / 1000000.0,
                3,
            )
        self._current_response = None
        self._waiting_for = "phase"
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
                "requested_relay_state": requested_state,
                "allowed_keys": phase.allowed_keys,
                "collect_response": phase.collect_response,
                "end_on_response": phase.end_on_response,
                "run_if_response_key": phase.run_if_response_key,
            },
        )

        if phase.duration_ms is None:
            self._scheduled_phase_start_ns = None
            self._after_id = None
            return
        self._scheduled_phase_start_ns = (
            self._phase_start_ns + phase.duration_ms * 1000000
        )
        remaining_ns = self._scheduled_phase_start_ns - time.perf_counter_ns()
        remaining_ms = max(1, (remaining_ns + 999999) // 1000000)
        self._after_id = self.window.after(
            remaining_ms, self._finish_current_phase
        )

    def _finish_current_phase(self, termination_reason="timer"):
        self._after_id = None
        phase = self._current_compiled_trial.trial.phases[self._phase_index]
        elapsed_ms = round(
            (time.perf_counter_ns() - self._phase_start_ns) / 1000000.0, 3
        )
        drift_ms = None
        if phase.duration_ms is not None and termination_reason == "timer":
            drift_ms = round(elapsed_ms - phase.duration_ms, 3)
        response = self._current_response or {}
        self._log_trial_event(
            "phase_end",
            scheduled_duration_ms=phase.duration_ms,
            elapsed_ms=elapsed_ms,
            drift_ms=drift_ms,
            lights=phase.lights,
            relay_state=phase.relay_states,
            response_key=response.get("key"),
            response_time_ms=response.get("response_time_ms"),
            correct=response.get("correct"),
            details={"termination_reason": termination_reason},
        )
        if (
            phase.collect_response
            and self._current_response is None
            and termination_reason == "timer"
        ):
            self._log_trial_event("response_timeout")
        if termination_reason == "response" or phase.duration_ms is None:
            self._scheduled_phase_start_ns = time.perf_counter_ns()
        self._run_next_phase()

    def _finish_current_trial(self):
        try:
            actual_state = self._set_all_off()
        except RelayError as exc:
            self._fail_experiment(exc)
            return
        self._log_trial_event("trial_end", relay_state=actual_state)
        self._begin_next_trial()

    def _set_all_off(self):
        requested_state = (0, 0, 0, 0)
        self.controller.set_states(requested_state)
        actual_state = tuple(self.controller.get_states())
        if actual_state != requested_state:
            raise RelayError(
                "Relay shutdown readback mismatch: requested {0}, received {1}.".format(
                    requested_state, actual_state
                )
            )
        return actual_state

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

    def _complete_experiment(self):
        try:
            actual_state = self._set_all_off()
        except RelayError as exc:
            self._fail_experiment(exc)
            return
        self.logger.log("session_complete", relay_state=actual_state)
        self.logger.finalize("completed")
        summary = self.logger.summary
        self.logger.close()
        self._waiting_for = "complete"
        accuracy = summary["accuracy_percent"]
        mean_response_time = summary["mean_response_time_ms"]
        accuracy_text = "n/a" if accuracy is None else "{0:.1f}%".format(accuracy)
        mean_rt_text = (
            "n/a"
            if mean_response_time is None
            else "{0:.1f} ms".format(mean_response_time)
        )
        pebt_summary = ""
        if self.config.task_type == "pebt":
            pebt_percent = summary["pro_environmental_choice_percent"]
            pebt_percent_text = (
                "n/a" if pebt_percent is None else "{0:.1f}%".format(pebt_percent)
            )
            set_counts = summary["choice_counts_by_set"]
            set1_sest = set_counts.get("SET1", {}).get("SEST", 0)
            set2_sest = set_counts.get("SET2", {}).get("SEST", 0)
            improvement = summary["pebt_improvement_set2_minus_set1"]
            improvement_text = "n/a" if improvement is None else str(improvement)
            pebt_summary = (
                "Pilihan SEST: {0} | DIFT: {1} | PEB: {2}\n"
                "SEST SET1: {3} | SEST SET2: {4} | Perubahan: {5}\n"
            ).format(
                summary["pro_environmental_choice_count"],
                summary["environmentally_harmful_choice_count"],
                pebt_percent_text,
                set1_sest,
                set2_sest,
                improvement_text,
            )
        completion_text = (
            "Eksperimen selesai\n\n"
            "Trial selesai: {0}/{1}\n"
            "Respons: {2} | Akurasi: {3} | RT rata-rata: {4}\n"
            "Timeout: {5}\n"
            "{6}\n"
            "Event log:\n{7}\n\n"
            "Ringkasan sesi:\n{8}"
        ).format(
            summary["completed_trial_count"],
            summary["planned_trial_count"],
            summary["response_count"],
            accuracy_text,
            mean_rt_text,
            summary["response_timeout_count"],
            pebt_summary,
            self.result_path,
            self.summary_path,
        )
        self._show_text_display(
            completion_text,
            self.config.display.background,
            self.config.display.foreground,
            18,
        )
        self.progress_label.configure(text="SELESAI")
        self.hint_label.configure(text="Tekan SPASI atau ENTER untuk menutup")

    def _fail_experiment(self, error):
        if self._after_id is not None:
            self.window.after_cancel(self._after_id)
            self._after_id = None
        error_details = {"error": str(error)}
        try:
            self._set_all_off()
        except RelayError as shutdown_error:
            error_details["shutdown_error"] = str(shutdown_error)
        self.logger.log("session_error", details=error_details)
        self.logger.finalize("error", details=error_details)
        self.logger.close()
        self._close_window("error")
        messagebox.showerror(
            "Eksperimen Dihentikan",
            "Eksperimen dihentikan karena error:\n\n{0}\n\nData parsial tersimpan di:\n{1}".format(
                error, self.result_path
            ),
            parent=self.parent,
        )

    def request_abort(self):
        if self._closed:
            return
        if self._waiting_for == "complete":
            self._close_window("completed")
            return
        if not messagebox.askyesno(
            "Batalkan Eksperimen",
            "Batalkan eksperimen? Data parsial tetap akan disimpan.",
            parent=self.window,
        ):
            return
        if self._after_id is not None:
            self.window.after_cancel(self._after_id)
            self._after_id = None
        abort_details = {}
        try:
            actual_state = self._set_all_off()
        except RelayError as shutdown_error:
            actual_state = None
            abort_details["shutdown_error"] = str(shutdown_error)
        self.logger.log(
            "session_aborted",
            relay_state=actual_state,
            details=abort_details or None,
        )
        self.logger.finalize("aborted", details=abort_details)
        self.logger.close()
        self._close_window("aborted")

    def _close_window(self, result):
        if self._closed:
            return
        self._closed = True
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.window.destroy()
        if self.on_finished is not None:
            self.on_finished(result, self.result_path)


class ExperimentSetupPanel(tk.Frame):
    """Operator form for validating and starting an experiment protocol."""

    def __init__(
        self,
        master,
        controller,
        connect_callback,
        status_callback,
        demo_mode=False,
    ):
        tk.Frame.__init__(self, master, bg=PANEL_COLORS["background"])
        self.controller = controller
        self.connect_callback = connect_callback
        self.status_callback = status_callback
        self.demo_mode = demo_mode
        self.config = None
        self.runner = None

        default_config = (
            Path(__file__).resolve().parent
            / "configs"
            / "pebt_yamawaki_2023_draft.json"
        )
        self.config_path_var = tk.StringVar(value=str(default_config))
        self.participant_var = tk.StringVar()
        self.session_var = tk.StringVar(value="S1")
        self.condition_var = tk.StringVar()
        self._build()
        self.load_config(show_error=False)

    def _build(self):
        content = tk.Frame(self, bg=PANEL_COLORS["background"], padx=28, pady=24)
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)

        setup = tk.Frame(
            content,
            bg=PANEL_COLORS["surface"],
            highlightbackground=PANEL_COLORS["line"],
            highlightthickness=1,
            padx=24,
            pady=22,
        )
        setup.grid(row=0, column=0, padx=(0, 14), sticky="nsew")

        tk.Label(
            setup,
            text="JALANKAN EKSPERIMEN",
            bg=PANEL_COLORS["surface"],
            fg=PANEL_COLORS["navy"],
            font=("Segoe UI Semibold", 15),
        ).pack(anchor="w")
        tk.Label(
            setup,
            text="Konfigurasi menggantikan sequence, loop, variable, dan logger OpenSesame.",
            bg=PANEL_COLORS["surface"],
            fg=PANEL_COLORS["muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(3, 16))

        self._field_label(setup, "File konfigurasi JSON")
        config_row = tk.Frame(setup, bg=PANEL_COLORS["surface"])
        config_row.pack(fill="x", pady=(0, 12))
        self.config_entry = tk.Entry(
            config_row,
            textvariable=self.config_path_var,
            font=("Segoe UI", 9),
            relief="solid",
            bd=1,
        )
        self.config_entry.pack(side="left", fill="x", expand=True, ipady=6)
        tk.Button(
            config_row,
            text="PILIH...",
            command=self.choose_config,
            bg="#EEF3F8",
            fg=PANEL_COLORS["navy"],
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            padx=12,
            pady=6,
        ).pack(side="left", padx=(8, 0))

        self._field_label(setup, "ID partisipan")
        tk.Entry(
            setup,
            textvariable=self.participant_var,
            font=("Segoe UI", 11),
            relief="solid",
            bd=1,
        ).pack(fill="x", ipady=7, pady=(0, 12))

        self._field_label(setup, "Label sesi")
        tk.Entry(
            setup,
            textvariable=self.session_var,
            font=("Segoe UI", 11),
            relief="solid",
            bd=1,
        ).pack(fill="x", ipady=7, pady=(0, 12))

        self._field_label(setup, "Kondisi antar-partisipan")
        self.condition_combo = ttk.Combobox(
            setup,
            textvariable=self.condition_var,
            values=(),
            state="disabled",
            font=("Segoe UI", 10),
        )
        self.condition_combo.pack(fill="x", ipady=5, pady=(0, 16))

        tk.Button(
            setup,
            text="VALIDASI KONFIGURASI",
            command=self.load_config,
            bg=PANEL_COLORS["surface"],
            fg=PANEL_COLORS["navy"],
            activebackground="#EEF3F8",
            relief="solid",
            bd=1,
            cursor="hand2",
            font=("Segoe UI Semibold", 10),
            pady=9,
        ).pack(fill="x", pady=(0, 9))

        self.start_button = tk.Button(
            setup,
            text="MULAI EKSPERIMEN",
            command=self.start_experiment,
            bg=PANEL_COLORS["green"],
            fg="white",
            activebackground="#1F6D4C",
            activeforeground="white",
            disabledforeground="#9AA7B5",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 11),
            pady=12,
            state="disabled",
        )
        self.start_button.pack(fill="x")

        summary = tk.Frame(
            content,
            bg=PANEL_COLORS["surface"],
            highlightbackground=PANEL_COLORS["line"],
            highlightthickness=1,
            padx=24,
            pady=22,
        )
        summary.grid(row=0, column=1, sticky="nsew")
        tk.Label(
            summary,
            text="RINGKASAN PROTOKOL",
            bg=PANEL_COLORS["surface"],
            fg=PANEL_COLORS["navy"],
            font=("Segoe UI Semibold", 14),
        ).pack(anchor="w")

        self.protocol_status_label = tk.Label(
            summary,
            text="BELUM DIVALIDASI",
            bg=PANEL_COLORS["warning_background"],
            fg=PANEL_COLORS["warning"],
            font=("Segoe UI Semibold", 9),
            padx=10,
            pady=6,
        )
        self.protocol_status_label.pack(anchor="w", pady=(12, 12))

        self.summary_label = tk.Label(
            summary,
            text="Pilih file konfigurasi dan validasi.",
            bg=PANEL_COLORS["surface"],
            fg=PANEL_COLORS["muted"],
            justify="left",
            anchor="nw",
            wraplength=330,
            font=("Segoe UI", 10),
        )
        self.summary_label.pack(fill="both", expand=True, anchor="nw")

        tk.Label(
            summary,
            text=(
                "Manual / System Setup tersedia pada tab terpisah untuk "
                "diagnosis hardware, bukan untuk menjalankan protokol."
            ),
            bg=PANEL_COLORS["surface"],
            fg=PANEL_COLORS["muted"],
            justify="left",
            wraplength=330,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(18, 0))

    @staticmethod
    def _field_label(parent, text):
        tk.Label(
            parent,
            text=text,
            bg=PANEL_COLORS["surface"],
            fg=PANEL_COLORS["muted"],
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", pady=(0, 4))

    def choose_config(self):
        selected_path = filedialog.askopenfilename(
            parent=self,
            title="Pilih konfigurasi eksperimen",
            filetypes=(("JSON experiment", "*.json"), ("All files", "*.*")),
        )
        if selected_path:
            self.config_path_var.set(selected_path)
            self.load_config()

    def load_config(self, show_error=True):
        try:
            self.config = ExperimentConfig.load(self.config_path_var.get().strip())
        except ConfigurationError as exc:
            self.config = None
            self.condition_var.set("")
            self.condition_combo.configure(values=(), state="disabled")
            self.start_button.configure(state="disabled")
            self.protocol_status_label.configure(
                text="KONFIGURASI TIDAK VALID",
                bg="#FBEAEA",
                fg=PANEL_COLORS["danger"],
            )
            self.summary_label.configure(text=str(exc))
            if show_error:
                messagebox.showerror("Konfigurasi Tidak Valid", str(exc), parent=self)
            return False

        if self.config.participant_conditions:
            self.condition_combo.configure(
                values=self.config.participant_conditions,
                state="readonly",
            )
            if self.condition_var.get() not in self.config.participant_conditions:
                self.condition_var.set(self.config.participant_conditions[0])
        else:
            self.condition_var.set("")
            self.condition_combo.configure(values=(), state="disabled")

        duration_minimum_ms, duration_maximum_ms, response_gated = (
            self.config.duration_bounds_ms
        )
        duration_text = "{0:.1f} detik".format(duration_maximum_ms / 1000.0)
        if duration_minimum_ms != duration_maximum_ms:
            duration_text = "{0:.1f}-{1:.1f} detik".format(
                duration_minimum_ms / 1000.0,
                duration_maximum_ms / 1000.0,
            )
        if response_gated:
            duration_text += " + waktu memilih"
        phase_count = sum(
            block.repetitions
            * sum(len(trial.phases) for trial in block.trials)
            for block in self.config.blocks
        )
        status_labels = {
            "demo": "DEMO - BUKAN PROTOKOL RISET",
            "draft": "DRAFT - PERLU VALIDASI PENELITI",
            "validated": "PROTOKOL TERVALIDASI",
        }
        is_validated = self.config.protocol_status == "validated"
        self.protocol_status_label.configure(
            text=status_labels[self.config.protocol_status],
            bg=(
                "#E5F4ED"
                if is_validated
                else PANEL_COLORS["warning_background"]
            ),
            fg=PANEL_COLORS["green"] if is_validated else PANEL_COLORS["warning"],
        )
        self.summary_label.configure(
            text=(
                "{0}\n\n"
                "Protocol ID: {1}\n"
                "Tipe tugas: {2}\n"
                "Status: {3}\n"
                "Blok: {4}\n"
                "Trial total: {5}\n"
                "Halaman instruksi: {6}\n"
                "Fase total: {7}\n"
                "Durasi fase: {8}\n"
                "Random seed: {9}\n"
                "Kondisi: {10}\n\n"
                "Sumber: {11}\n\n"
                "{12}"
            ).format(
                self.config.title,
                self.config.protocol_id,
                self.config.task_type,
                self.config.protocol_status,
                len(self.config.blocks),
                self.config.trial_count,
                len(self.config.instruction_pages),
                phase_count,
                duration_text,
                self.config.random_seed,
                (
                    ", ".join(self.config.participant_conditions)
                    if self.config.participant_conditions
                    else "tidak digunakan"
                ),
                len(self.config.sources),
                self.config.description,
            )
        )
        self.start_button.configure(
            state="normal",
            text=(
                "MULAI EKSPERIMEN"
                if is_validated
                else "MULAI DEMO / DRAFT"
            ),
        )
        return True

    def start_experiment(self):
        if self.runner is not None:
            messagebox.showwarning(
                "Eksperimen Aktif",
                "Selesaikan atau batalkan eksperimen yang sedang berjalan.",
                parent=self,
            )
            return
        if self.config is None and not self.load_config():
            return

        participant_id = self.participant_var.get().strip()
        if not participant_id:
            messagebox.showerror(
                "ID Partisipan Wajib",
                "Masukkan ID partisipan sebelum memulai.",
                parent=self,
            )
            return

        participant_condition = self.condition_var.get().strip().lower()
        if (
            self.config.participant_conditions
            and participant_condition not in self.config.participant_conditions
        ):
            messagebox.showerror(
                "Kondisi Eksperimen Wajib",
                "Pilih kondisi antar-partisipan yang valid sebelum memulai.",
                parent=self,
            )
            return

        if self.config.protocol_status != "validated" and not self.demo_mode:
            proceed = messagebox.askyesno(
                "Protokol Belum Tervalidasi",
                "Konfigurasi berstatus {0} dan bukan protokol penelitian final. "
                "Jalankan hanya untuk pengujian sistem?".format(
                    self.config.protocol_status.upper()
                ),
                parent=self,
            )
            if not proceed:
                return

        if not self.controller.is_connected and not self.connect_callback():
            return

        try:
            self.runner = ExperimentRunnerWindow(
                self.winfo_toplevel(),
                config=self.config,
                participant_id=participant_id,
                session_label=self.session_var.get().strip(),
                participant_condition=participant_condition,
                controller=self.controller,
                on_finished=self._runner_finished,
            )
        except (ConfigurationError, OSError, RelayError) as exc:
            self.runner = None
            messagebox.showerror(
                "Eksperimen Tidak Dapat Dimulai", str(exc), parent=self
            )
            return
        self.status_callback(
            "Eksperimen aktif: {0}".format(self.config.protocol_id),
            connected=True,
        )

    def _runner_finished(self, result, data_path):
        self.runner = None
        self.status_callback(
            "Eksperimen {0}; data: {1}".format(result, data_path),
            connected=self.controller.is_connected,
        )
