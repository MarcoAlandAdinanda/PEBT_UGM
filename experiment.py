"""Configuration, planning, and data logging for the experiment runner."""

from __future__ import absolute_import

import csv
import hashlib
import json
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from relay_controller import relay_states_for_sides


SCHEMA_VERSION = 1
VALID_PROTOCOL_STATUSES = {"demo", "draft", "validated"}
VALID_TASK_TYPES = {"generic", "pebt"}
VALID_SIDES = {"left", "right", "front"}
VALID_SOURCE_TYPES = {
    "hardware_manual",
    "software_manual",
    "research_paper",
    "other",
}


class ConfigurationError(ValueError):
    """Raised when an experiment configuration is incomplete or invalid."""


def _require_mapping(value, path):
    if not isinstance(value, dict):
        raise ConfigurationError("{0} must be an object.".format(path))
    return value


def _require_string(value, path, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigurationError("{0} must be a non-empty string.".format(path))
    return value


def _require_int(value, path, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError("{0} must be an integer.".format(path))
    if minimum is not None and value < minimum:
        raise ConfigurationError("{0} must be at least {1}.".format(path, minimum))
    if maximum is not None and value > maximum:
        raise ConfigurationError("{0} must be at most {1}.".format(path, maximum))
    return value


def _require_bool(value, path):
    if not isinstance(value, bool):
        raise ConfigurationError("{0} must be true or false.".format(path))
    return value


@dataclass(frozen=True)
class DisplayConfig:
    fullscreen: bool = True
    background: str = "#000000"
    foreground: str = "#FFFFFF"
    font_size: int = 30


@dataclass(frozen=True)
class SourceReference:
    source_type: str
    title: str
    citation: str
    url: str
    pages: str
    notes: str


@dataclass(frozen=True)
class InstructionPage:
    page_id: str
    title: str
    text: str
    hint: str


@dataclass(frozen=True)
class PhaseDefinition:
    name: str
    duration_ms: object
    text: str
    lights: tuple
    collect_response: bool
    allowed_keys: tuple
    end_on_response: bool = False
    run_if_response_key: str = None
    background: str = None
    foreground: str = None
    font_size: int = None

    @property
    def relay_states(self):
        return relay_states_for_sides(
            left="left" in self.lights,
            right="right" in self.lights,
            front="front" in self.lights,
        )


@dataclass(frozen=True)
class TrialDefinition:
    trial_id: str
    condition: str
    correct_key: str
    phases: tuple
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BlockDefinition:
    block_id: str
    instructions: str
    repetitions: int
    randomize_trials: bool
    trials: tuple


@dataclass(frozen=True)
class CompiledTrial:
    block_index: int
    block_id: str
    block_instructions: str
    repetition: int
    trial_index: int
    trial: TrialDefinition


@dataclass(frozen=True)
class ExperimentConfig:
    schema_version: int
    task_type: str
    protocol_id: str
    title: str
    protocol_status: str
    description: str
    instructions: str
    random_seed: int
    data_directory: str
    display: DisplayConfig
    sources: tuple
    participant_conditions: tuple
    instruction_pages: tuple
    blocks: tuple
    source_path: str = None
    config_sha256: str = ""

    @classmethod
    def load(cls, path):
        source_path = Path(path).resolve()
        try:
            source_bytes = source_path.read_bytes()
            data = json.loads(source_bytes.decode("utf-8"))
        except OSError as exc:
            raise ConfigurationError("Cannot open configuration: {0}".format(exc))
        except UnicodeDecodeError as exc:
            raise ConfigurationError(
                "Configuration must be UTF-8 encoded: {0}".format(exc)
            )
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                "Invalid JSON at line {0}, column {1}: {2}".format(
                    exc.lineno, exc.colno, exc.msg
                )
            )
        return cls.from_dict(
            data,
            source_path=str(source_path),
            config_sha256=hashlib.sha256(source_bytes).hexdigest(),
        )

    @classmethod
    def from_dict(cls, data, source_path=None, config_sha256=None):
        data = _require_mapping(data, "configuration")
        if config_sha256 is None:
            canonical_json = json.dumps(
                data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            config_sha256 = hashlib.sha256(canonical_json).hexdigest()
        if data.get("generator") is not None:
            try:
                from pebt import PEBTGeneratorError, expand_pebt_configuration

                data = expand_pebt_configuration(data)
            except PEBTGeneratorError as exc:
                raise ConfigurationError("PEBT generator: {0}".format(exc))
        schema_version = _require_int(
            data.get("schema_version"), "schema_version", minimum=1
        )
        if schema_version != SCHEMA_VERSION:
            raise ConfigurationError(
                "Unsupported schema_version {0}; expected {1}.".format(
                    schema_version, SCHEMA_VERSION
                )
            )

        task_type = _require_string(
            data.get("task_type", "generic"), "task_type"
        ).lower()
        if task_type not in VALID_TASK_TYPES:
            raise ConfigurationError(
                "task_type must be one of: {0}.".format(
                    ", ".join(sorted(VALID_TASK_TYPES))
                )
            )

        protocol_id = _require_string(data.get("protocol_id"), "protocol_id")
        title = _require_string(data.get("title"), "title")
        protocol_status = _require_string(
            data.get("protocol_status"), "protocol_status"
        ).lower()
        if protocol_status not in VALID_PROTOCOL_STATUSES:
            raise ConfigurationError(
                "protocol_status must be one of: {0}.".format(
                    ", ".join(sorted(VALID_PROTOCOL_STATUSES))
                )
            )
        description = _require_string(
            data.get("description", ""), "description", allow_empty=True
        )
        instructions = _require_string(data.get("instructions"), "instructions")
        random_seed = _require_int(data.get("random_seed", 0), "random_seed")
        data_directory = _require_string(
            data.get("data_directory", "data/experiments"), "data_directory"
        )

        participant_conditions_data = data.get("participant_conditions", [])
        if not isinstance(participant_conditions_data, list):
            raise ConfigurationError("participant_conditions must be an array.")
        participant_conditions = []
        for condition_index, condition_name in enumerate(
            participant_conditions_data
        ):
            condition_name = _require_string(
                condition_name,
                "participant_conditions[{0}]".format(condition_index),
            ).lower()
            if condition_name in participant_conditions:
                raise ConfigurationError(
                    "participant_conditions contains duplicate {0}.".format(
                        condition_name
                    )
                )
            participant_conditions.append(condition_name)
        if task_type == "pebt" and not participant_conditions:
            raise ConfigurationError(
                "A PEBT protocol must define participant_conditions."
            )

        instruction_pages_data = data.get("instruction_pages", [])
        if not isinstance(instruction_pages_data, list):
            raise ConfigurationError("instruction_pages must be an array.")
        instruction_pages = []
        known_instruction_page_ids = set()
        for page_index, page_data in enumerate(instruction_pages_data):
            page_path = "instruction_pages[{0}]".format(page_index)
            page_data = _require_mapping(page_data, page_path)
            page_id = _require_string(
                page_data.get("page_id"), page_path + ".page_id"
            )
            if page_id in known_instruction_page_ids:
                raise ConfigurationError(
                    "instruction_pages page_id must be unique; duplicate: {0}.".format(
                        page_id
                    )
                )
            known_instruction_page_ids.add(page_id)
            instruction_pages.append(
                InstructionPage(
                    page_id=page_id,
                    title=_require_string(
                        page_data.get("title"), page_path + ".title"
                    ),
                    text=_require_string(page_data.get("text"), page_path + ".text"),
                    hint=_require_string(
                        page_data.get("hint", "Tekan SPASI untuk melanjutkan"),
                        page_path + ".hint",
                    ),
                )
            )
        if not instruction_pages:
            instruction_pages.append(
                InstructionPage(
                    page_id="overview",
                    title=title,
                    text=instructions,
                    hint="Tekan SPASI untuk memulai eksperimen",
                )
            )

        display_data = _require_mapping(data.get("display", {}), "display")
        display = DisplayConfig(
            fullscreen=_require_bool(
                display_data.get("fullscreen", True), "display.fullscreen"
            ),
            background=_require_string(
                display_data.get("background", "#000000"), "display.background"
            ),
            foreground=_require_string(
                display_data.get("foreground", "#FFFFFF"), "display.foreground"
            ),
            font_size=_require_int(
                display_data.get("font_size", 30),
                "display.font_size",
                minimum=8,
                maximum=200,
            ),
        )

        sources_data = data.get("sources", [])
        if not isinstance(sources_data, list):
            raise ConfigurationError("sources must be an array.")
        sources = []
        for source_index, source_data in enumerate(sources_data):
            source_path_label = "sources[{0}]".format(source_index)
            source_data = _require_mapping(source_data, source_path_label)
            source_type = _require_string(
                source_data.get("source_type"),
                source_path_label + ".source_type",
            ).lower()
            if source_type not in VALID_SOURCE_TYPES:
                raise ConfigurationError(
                    "{0}.source_type must be one of: {1}.".format(
                        source_path_label, ", ".join(sorted(VALID_SOURCE_TYPES))
                    )
                )
            sources.append(
                SourceReference(
                    source_type=source_type,
                    title=_require_string(
                        source_data.get("title"), source_path_label + ".title"
                    ),
                    citation=_require_string(
                        source_data.get("citation", ""),
                        source_path_label + ".citation",
                        allow_empty=True,
                    ),
                    url=_require_string(
                        source_data.get("url", ""),
                        source_path_label + ".url",
                        allow_empty=True,
                    ),
                    pages=_require_string(
                        source_data.get("pages", ""),
                        source_path_label + ".pages",
                        allow_empty=True,
                    ),
                    notes=_require_string(
                        source_data.get("notes", ""),
                        source_path_label + ".notes",
                        allow_empty=True,
                    ),
                )
            )
        if protocol_status == "validated" and not any(
            source.source_type == "research_paper" for source in sources
        ):
            raise ConfigurationError(
                "A validated protocol must include a research_paper in sources."
            )

        blocks_data = data.get("blocks")
        if not isinstance(blocks_data, list) or not blocks_data:
            raise ConfigurationError("blocks must be a non-empty array.")

        blocks = []
        known_trial_ids = set()
        for block_index, block_data in enumerate(blocks_data):
            block_path = "blocks[{0}]".format(block_index)
            block_data = _require_mapping(block_data, block_path)
            block_id = _require_string(
                block_data.get("block_id"), block_path + ".block_id"
            )
            block_instructions = _require_string(
                block_data.get("instructions", "Tekan SPASI untuk melanjutkan."),
                block_path + ".instructions",
            )
            repetitions = _require_int(
                block_data.get("repetitions", 1),
                block_path + ".repetitions",
                minimum=1,
                maximum=10000,
            )
            randomize_trials = _require_bool(
                block_data.get("randomize_trials", False),
                block_path + ".randomize_trials",
            )
            trials_data = block_data.get("trials")
            if not isinstance(trials_data, list) or not trials_data:
                raise ConfigurationError(
                    "{0}.trials must be a non-empty array.".format(block_path)
                )

            trials = []
            for trial_offset, trial_data in enumerate(trials_data):
                trial_path = "{0}.trials[{1}]".format(block_path, trial_offset)
                trial_data = _require_mapping(trial_data, trial_path)
                trial_id = _require_string(
                    trial_data.get("trial_id"), trial_path + ".trial_id"
                )
                if trial_id in known_trial_ids:
                    raise ConfigurationError(
                        "trial_id must be unique; duplicate: {0}.".format(trial_id)
                    )
                known_trial_ids.add(trial_id)
                condition = _require_string(
                    trial_data.get("condition", trial_id), trial_path + ".condition"
                )
                correct_key_value = trial_data.get("correct_key")
                correct_key = None
                if correct_key_value is not None:
                    correct_key = _require_string(
                        correct_key_value, trial_path + ".correct_key"
                    ).lower()
                metadata = _require_mapping(
                    trial_data.get("metadata", {}), trial_path + ".metadata"
                )

                phases_data = trial_data.get("phases")
                if not isinstance(phases_data, list) or not phases_data:
                    raise ConfigurationError(
                        "{0}.phases must be a non-empty array.".format(trial_path)
                    )
                phases = []
                response_keys = set()
                for phase_index, phase_data in enumerate(phases_data):
                    phase_path = "{0}.phases[{1}]".format(trial_path, phase_index)
                    phase_data = _require_mapping(phase_data, phase_path)
                    phase_name = _require_string(
                        phase_data.get("name"), phase_path + ".name"
                    )
                    duration_value = phase_data.get("duration_ms")
                    phase_text = _require_string(
                        phase_data.get("text", ""),
                        phase_path + ".text",
                        allow_empty=True,
                    )

                    lights_data = phase_data.get("lights", [])
                    if not isinstance(lights_data, list):
                        raise ConfigurationError(
                            "{0}.lights must be an array.".format(phase_path)
                        )
                    lights = []
                    for light_offset, light_name in enumerate(lights_data):
                        light_name = _require_string(
                            light_name,
                            "{0}.lights[{1}]".format(phase_path, light_offset),
                        ).lower()
                        if light_name not in VALID_SIDES:
                            raise ConfigurationError(
                                "{0}.lights contains {1}; allowed: {2}.".format(
                                    phase_path,
                                    light_name,
                                    ", ".join(sorted(VALID_SIDES)),
                                )
                            )
                        if light_name in lights:
                            raise ConfigurationError(
                                "{0}.lights contains duplicate {1}.".format(
                                    phase_path, light_name
                                )
                            )
                        lights.append(light_name)

                    collect_response = _require_bool(
                        phase_data.get("collect_response", False),
                        phase_path + ".collect_response",
                    )
                    allowed_keys_data = phase_data.get("allowed_keys", [])
                    if not isinstance(allowed_keys_data, list):
                        raise ConfigurationError(
                            "{0}.allowed_keys must be an array.".format(phase_path)
                        )
                    allowed_keys = tuple(
                        _require_string(
                            key,
                            "{0}.allowed_keys[{1}]".format(phase_path, key_index),
                        ).lower()
                        for key_index, key in enumerate(allowed_keys_data)
                    )
                    if collect_response and not allowed_keys:
                        raise ConfigurationError(
                            "{0} collects a response but has no allowed_keys.".format(
                                phase_path
                            )
                        )
                    if not collect_response and allowed_keys:
                        raise ConfigurationError(
                            "{0} has allowed_keys but collect_response is false.".format(
                                phase_path
                            )
                        )
                    end_on_response = _require_bool(
                        phase_data.get("end_on_response", False),
                        phase_path + ".end_on_response",
                    )
                    if end_on_response and not collect_response:
                        raise ConfigurationError(
                            "{0} ends on response but does not collect a response.".format(
                                phase_path
                            )
                        )
                    if duration_value is None:
                        if not (collect_response and end_on_response):
                            raise ConfigurationError(
                                "{0}.duration_ms may be null only for a response-gated "
                                "phase with end_on_response true.".format(phase_path)
                            )
                        duration_ms = None
                    else:
                        duration_ms = _require_int(
                            duration_value,
                            phase_path + ".duration_ms",
                            minimum=1,
                            maximum=86400000,
                        )
                    run_if_response_key = phase_data.get("run_if_response_key")
                    if run_if_response_key is not None:
                        run_if_response_key = _require_string(
                            run_if_response_key,
                            phase_path + ".run_if_response_key",
                        ).lower()
                        if collect_response:
                            raise ConfigurationError(
                                "{0} cannot collect a response and be conditional on a "
                                "previous response.".format(phase_path)
                            )
                        if run_if_response_key not in response_keys:
                            raise ConfigurationError(
                                "{0}.run_if_response_key must match a response option "
                                "from an earlier phase.".format(phase_path)
                            )
                    response_keys.update(allowed_keys)

                    background = phase_data.get("background")
                    if background is not None:
                        background = _require_string(
                            background, phase_path + ".background"
                        )
                    foreground = phase_data.get("foreground")
                    if foreground is not None:
                        foreground = _require_string(
                            foreground, phase_path + ".foreground"
                        )
                    font_size = phase_data.get("font_size")
                    if font_size is not None:
                        font_size = _require_int(
                            font_size,
                            phase_path + ".font_size",
                            minimum=8,
                            maximum=200,
                        )

                    phases.append(
                        PhaseDefinition(
                            name=phase_name,
                            duration_ms=duration_ms,
                            text=phase_text,
                            lights=tuple(lights),
                            collect_response=collect_response,
                            allowed_keys=allowed_keys,
                            end_on_response=end_on_response,
                            run_if_response_key=run_if_response_key,
                            background=background,
                            foreground=foreground,
                            font_size=font_size,
                        )
                    )

                conditional_keys = {
                    phase.run_if_response_key
                    for phase in phases
                    if phase.run_if_response_key is not None
                }
                unknown_conditional_keys = conditional_keys - response_keys
                if unknown_conditional_keys:
                    raise ConfigurationError(
                        "{0} uses run_if_response_key values without an earlier "
                        "response option: {1}.".format(
                            trial_path,
                            ", ".join(sorted(unknown_conditional_keys)),
                        )
                    )
                if correct_key is not None and correct_key not in response_keys:
                    raise ConfigurationError(
                        "{0}.correct_key is not present in a response phase.".format(
                            trial_path
                        )
                    )

                trials.append(
                    TrialDefinition(
                        trial_id=trial_id,
                        condition=condition,
                        correct_key=correct_key,
                        phases=tuple(phases),
                        metadata=dict(metadata),
                    )
                )

            blocks.append(
                BlockDefinition(
                    block_id=block_id,
                    instructions=block_instructions,
                    repetitions=repetitions,
                    randomize_trials=randomize_trials,
                    trials=tuple(trials),
                )
            )

        return cls(
            schema_version=schema_version,
            task_type=task_type,
            protocol_id=protocol_id,
            title=title,
            protocol_status=protocol_status,
            description=description,
            instructions=instructions,
            random_seed=random_seed,
            data_directory=data_directory,
            display=display,
            sources=tuple(sources),
            participant_conditions=tuple(participant_conditions),
            instruction_pages=tuple(instruction_pages),
            blocks=tuple(blocks),
            source_path=source_path,
            config_sha256=config_sha256,
        )

    @property
    def trial_count(self):
        return sum(block.repetitions * len(block.trials) for block in self.blocks)

    @property
    def duration_bounds_ms(self):
        minimum_total = 0
        maximum_total = 0
        has_response_gated_phase = False
        for block in self.blocks:
            block_minimum = 0
            block_maximum = 0
            for trial in block.trials:
                trial_minimum = 0
                trial_maximum = 0
                phase_index = 0
                while phase_index < len(trial.phases):
                    phase = trial.phases[phase_index]
                    if phase.run_if_response_key is None:
                        if phase.duration_ms is None:
                            has_response_gated_phase = True
                        else:
                            trial_minimum += phase.duration_ms
                            trial_maximum += phase.duration_ms
                        phase_index += 1
                        continue

                    branch_durations = {}
                    while (
                        phase_index < len(trial.phases)
                        and trial.phases[phase_index].run_if_response_key is not None
                    ):
                        branch_phase = trial.phases[phase_index]
                        branch_key = branch_phase.run_if_response_key
                        branch_durations.setdefault(branch_key, 0)
                        if branch_phase.duration_ms is None:
                            has_response_gated_phase = True
                        else:
                            branch_durations[branch_key] += branch_phase.duration_ms
                        phase_index += 1
                    trial_minimum += min(branch_durations.values())
                    trial_maximum += max(branch_durations.values())
                block_minimum += trial_minimum
                block_maximum += trial_maximum
            minimum_total += block.repetitions * block_minimum
            maximum_total += block.repetitions * block_maximum
        return minimum_total, maximum_total, has_response_gated_phase

    @property
    def estimated_duration_ms(self):
        return self.duration_bounds_ms[1]

    def compile_trials(self, participant_id):
        participant_id = _require_string(participant_id, "participant_id")
        compiled = []
        trial_index = 0
        for block_index, block in enumerate(self.blocks):
            for repetition in range(1, block.repetitions + 1):
                ordered_trials = list(block.trials)
                if block.randomize_trials:
                    seed_text = "{0}|{1}|{2}|{3}".format(
                        self.random_seed, participant_id, block.block_id, repetition
                    )
                    seed_value = int.from_bytes(
                        hashlib.sha256(seed_text.encode("utf-8")).digest()[:8],
                        "big",
                    )
                    random.Random(seed_value).shuffle(ordered_trials)
                for trial in ordered_trials:
                    trial_index += 1
                    compiled.append(
                        CompiledTrial(
                            block_index=block_index,
                            block_id=block.block_id,
                            block_instructions=block.instructions,
                            repetition=repetition,
                            trial_index=trial_index,
                            trial=trial,
                        )
                    )
        return tuple(compiled)


class ExperimentLogger(object):
    """Append-only event log plus an atomic, reproducible session summary."""

    FIELDNAMES = (
        "timestamp_utc",
        "monotonic_ms",
        "session_id",
        "participant_id",
        "session_label",
        "participant_condition",
        "protocol_id",
        "protocol_status",
        "config_path",
        "config_sha256",
        "event",
        "block_index",
        "block_id",
        "repetition",
        "trial_index",
        "trial_id",
        "condition",
        "phase_index",
        "phase_name",
        "scheduled_duration_ms",
        "elapsed_ms",
        "drift_ms",
        "lights",
        "relay_state",
        "response_key",
        "response_time_ms",
        "correct",
        "details_json",
    )

    def __init__(
        self,
        config,
        participant_id,
        session_label="",
        participant_condition="",
        output_directory=None,
        compiled_trials=None,
        clock_ns=None,
        now_utc=None,
    ):
        self.config = config
        self.participant_id = _require_string(participant_id, "participant_id")
        self.session_label = session_label.strip()
        self.participant_condition = participant_condition.strip().lower()
        if config.participant_conditions:
            if self.participant_condition not in config.participant_conditions:
                raise ConfigurationError(
                    "participant_condition must be one of: {0}.".format(
                        ", ".join(config.participant_conditions)
                    )
                )
        elif self.participant_condition:
            raise ConfigurationError(
                "This protocol does not define participant_conditions."
            )
        self.session_id = str(uuid.uuid4())
        self._clock_ns = clock_ns or time.perf_counter_ns
        self._now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self._started_ns = self._clock_ns()
        self._started_at_utc = self._now_utc()
        self._event_count = 0
        self._response_count = 0
        self._scored_response_count = 0
        self._correct_response_count = 0
        self._incorrect_response_count = 0
        self._response_timeout_count = 0
        self._completed_trial_count = 0
        self._response_time_total_ms = 0.0
        self._response_time_count = 0
        self._choice_counts = {}
        self._choice_counts_by_condition = {}
        self._choice_counts_by_set = {}
        self._pro_environmental_choice_count = 0
        self._environmentally_harmful_choice_count = 0
        self._finalized = False
        self._final_status = "in_progress"
        self._final_details = {}
        self._compiled_trials = tuple(compiled_trials or ())

        output_path = Path(output_directory or config.data_directory)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = self._started_at_utc.strftime("%Y%m%dT%H%M%SZ")
        basename = "{0}_{1}_{2}_{3}".format(
            timestamp,
            self._safe_component(participant_id),
            self._safe_component(config.protocol_id),
            self.session_id[:8],
        )
        self.path = (output_path / (basename + ".events.csv")).resolve()
        self.summary_path = (output_path / (basename + ".summary.json")).resolve()
        self._file = self.path.open("x", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDNAMES)
        self._writer.writeheader()
        self._file.flush()
        self._write_summary(status="in_progress")

    @staticmethod
    def _safe_component(value):
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
        return cleaned.strip("._-") or "unnamed"

    def log(self, event, **values):
        row = {field_name: "" for field_name in self.FIELDNAMES}
        row.update(
            {
                "timestamp_utc": self._now_utc().isoformat(),
                "monotonic_ms": round(
                    (self._clock_ns() - self._started_ns) / 1000000.0, 3
                ),
                "session_id": self.session_id,
                "participant_id": self.participant_id,
                "session_label": self.session_label,
                "participant_condition": self.participant_condition,
                "protocol_id": self.config.protocol_id,
                "protocol_status": self.config.protocol_status,
                "config_path": self.config.source_path or "",
                "config_sha256": self.config.config_sha256,
                "event": event,
            }
        )
        details = values.pop("details", None)
        for key, value in values.items():
            if key not in row:
                raise ValueError("Unknown log field: {0}".format(key))
            if isinstance(value, (tuple, list)):
                row[key] = json.dumps(value, ensure_ascii=False)
            elif value is not None:
                row[key] = value
        if details is not None:
            row["details_json"] = json.dumps(
                details, ensure_ascii=False, sort_keys=True
            )
        self._writer.writerow(row)
        self._file.flush()
        self._update_metrics(event, row)

    def _update_metrics(self, event, row):
        self._event_count += 1
        if event == "response":
            self._response_count += 1
            response_time = row.get("response_time_ms")
            if response_time not in (None, ""):
                self._response_time_total_ms += float(response_time)
                self._response_time_count += 1
            correct = row.get("correct")
            if correct is True:
                self._scored_response_count += 1
                self._correct_response_count += 1
            elif correct is False:
                self._scored_response_count += 1
                self._incorrect_response_count += 1
            details = {}
            if row.get("details_json"):
                details = json.loads(row["details_json"])
            choice_label = details.get("choice_label")
            if choice_label:
                self._choice_counts.setdefault(choice_label, 0)
                self._choice_counts[choice_label] += 1
                condition = row.get("condition") or "unspecified"
                self._choice_counts_by_condition.setdefault(condition, {})
                condition_counts = self._choice_counts_by_condition[condition]
                condition_counts.setdefault(choice_label, 0)
                condition_counts[choice_label] += 1
                set_id = details.get("set_id")
                if set_id:
                    self._choice_counts_by_set.setdefault(set_id, {})
                    set_counts = self._choice_counts_by_set[set_id]
                    set_counts.setdefault(choice_label, 0)
                    set_counts[choice_label] += 1
            pro_environmental = details.get("pro_environmental")
            if pro_environmental is True:
                self._pro_environmental_choice_count += 1
            elif pro_environmental is False:
                self._environmentally_harmful_choice_count += 1
        elif event == "response_timeout":
            self._response_timeout_count += 1
        elif event == "trial_end":
            self._completed_trial_count += 1

    @property
    def summary(self):
        accuracy_percent = None
        if self._scored_response_count:
            accuracy_percent = round(
                100.0
                * self._correct_response_count
                / self._scored_response_count,
                3,
            )
        mean_response_time_ms = None
        if self._response_time_count:
            mean_response_time_ms = round(
                self._response_time_total_ms / self._response_time_count,
                3,
            )
        pebt_choice_count = (
            self._pro_environmental_choice_count
            + self._environmentally_harmful_choice_count
        )
        pro_environmental_choice_percent = None
        if pebt_choice_count:
            pro_environmental_choice_percent = round(
                100.0 * self._pro_environmental_choice_count / pebt_choice_count,
                3,
            )
        set1_counts = self._choice_counts_by_set.get("SET1")
        set2_counts = self._choice_counts_by_set.get("SET2")
        pebt_improvement = None
        if set1_counts is not None and set2_counts is not None:
            pebt_improvement = set2_counts.get("SEST", 0) - set1_counts.get(
                "SEST", 0
            )
        return {
            "event_count": self._event_count,
            "planned_trial_count": len(self._compiled_trials),
            "completed_trial_count": self._completed_trial_count,
            "response_count": self._response_count,
            "scored_response_count": self._scored_response_count,
            "correct_response_count": self._correct_response_count,
            "incorrect_response_count": self._incorrect_response_count,
            "response_timeout_count": self._response_timeout_count,
            "accuracy_percent": accuracy_percent,
            "mean_response_time_ms": mean_response_time_ms,
            "choice_counts": dict(self._choice_counts),
            "choice_counts_by_condition": {
                condition: dict(counts)
                for condition, counts in self._choice_counts_by_condition.items()
            },
            "choice_counts_by_set": {
                set_id: dict(counts)
                for set_id, counts in self._choice_counts_by_set.items()
            },
            "pebt_improvement_set2_minus_set1": pebt_improvement,
            "pro_environmental_choice_count": self._pro_environmental_choice_count,
            "environmentally_harmful_choice_count": (
                self._environmentally_harmful_choice_count
            ),
            "pro_environmental_choice_percent": (
                pro_environmental_choice_percent
            ),
        }

    def _trial_order(self):
        return [
            {
                "block_index": item.block_index,
                "block_id": item.block_id,
                "repetition": item.repetition,
                "trial_index": item.trial_index,
                "trial_id": item.trial.trial_id,
                "condition": item.trial.condition,
            }
            for item in self._compiled_trials
        ]

    def _write_summary(self, status, finished_at_utc=None, details=None):
        payload = {
            "schema_version": 1,
            "session_id": self.session_id,
            "status": status,
            "started_at_utc": self._started_at_utc.isoformat(),
            "finished_at_utc": finished_at_utc,
            "participant_id": self.participant_id,
            "session_label": self.session_label,
            "participant_condition": self.participant_condition,
            "protocol": {
                "task_type": self.config.task_type,
                "protocol_id": self.config.protocol_id,
                "title": self.config.title,
                "status": self.config.protocol_status,
                "config_path": self.config.source_path or "",
                "config_sha256": self.config.config_sha256,
            },
            "event_log": self.path.name,
            "trial_order": self._trial_order(),
            "metrics": self.summary,
            "details": details or {},
        }
        temporary_path = self.summary_path.with_suffix(
            self.summary_path.suffix + ".tmp"
        )
        with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary_path.replace(self.summary_path)

    def finalize(self, status, details=None):
        if status not in ("completed", "aborted", "error"):
            raise ValueError("Unknown final session status: {0}".format(status))
        if self._finalized:
            return
        self._finalized = True
        self._final_status = status
        self._final_details = dict(details or {})
        self._write_summary(
            status=status,
            finished_at_utc=self._now_utc().isoformat(),
            details=self._final_details,
        )

    def close(self):
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
