"""Visual experiment builder and editable JSON-backed draft model."""

from __future__ import absolute_import

import copy
import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from experiment import ConfigurationError, ExperimentConfig
from pebt import PEBTGeneratorError, expand_pebt_configuration


BUILDER_COLORS = {
    "background": "#F3F6FA",
    "surface": "#FFFFFF",
    "navy": "#17324D",
    "muted": "#62748A",
    "line": "#D7E0EA",
    "green": "#25835B",
    "warning": "#A56700",
    "danger": "#B64242",
}


class BuilderError(ValueError):
    """Raised when an editable experiment cannot be loaded or manipulated."""


def _split_csv(value):
    return [item.strip().lower() for item in value.split(",") if item.strip()]


class ExperimentDraft(object):
    """Mutable experiment document used by the visual builder."""

    def __init__(
        self,
        data,
        file_path=None,
        source_path=None,
        expanded_from_generator=False,
    ):
        if not isinstance(data, dict):
            raise BuilderError("Experiment document must be a JSON object.")
        self.data = copy.deepcopy(data)
        self.file_path = Path(file_path).resolve() if file_path else None
        self.source_path = Path(source_path).resolve() if source_path else None
        self.expanded_from_generator = bool(expanded_from_generator)
        self.is_dirty = False

    @classmethod
    def new(cls):
        return cls(
            {
                "schema_version": 1,
                "task_type": "generic",
                "protocol_id": "NEW-EXPERIMENT-V1",
                "title": "Eksperimen Baru",
                "protocol_status": "draft",
                "description": "Dibuat dengan PEBT UGM Experiment Builder.",
                "instructions": "Tekan SPASI untuk memulai eksperimen.",
                "instruction_pages": [],
                "random_seed": 2026,
                "data_directory": "data/experiments",
                "participant_conditions": [],
                "display": {
                    "fullscreen": False,
                    "background": "#101820",
                    "foreground": "#FFFFFF",
                    "font_size": 34,
                },
                "sources": [],
                "blocks": [
                    {
                        "block_id": "block-1",
                        "instructions": "Tekan SPASI untuk memulai blok.",
                        "repetitions": 1,
                        "randomize_trials": False,
                        "trials": [
                            {
                                "trial_id": "trial-1",
                                "condition": "default",
                                "correct_key": None,
                                "metadata": {},
                                "phases": [
                                    {
                                        "name": "stimulus",
                                        "duration_ms": 1000,
                                        "text": "Stimulus",
                                        "lights": [],
                                        "collect_response": False,
                                        "allowed_keys": [],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )

    @classmethod
    def load(cls, path):
        source_path = Path(path).resolve()
        try:
            raw_bytes = source_path.read_bytes()
            data = json.loads(raw_bytes.decode("utf-8"))
        except OSError as exc:
            raise BuilderError("Cannot open experiment: {0}".format(exc))
        except UnicodeDecodeError as exc:
            raise BuilderError("Experiment must be UTF-8: {0}".format(exc))
        except json.JSONDecodeError as exc:
            raise BuilderError(
                "Invalid JSON at line {0}, column {1}: {2}".format(
                    exc.lineno, exc.colno, exc.msg
                )
            )
        if not isinstance(data, dict):
            raise BuilderError("Experiment document must be a JSON object.")

        expanded_from_generator = data.get("generator") is not None
        if expanded_from_generator:
            try:
                data = expand_pebt_configuration(data)
            except PEBTGeneratorError as exc:
                raise BuilderError("Cannot expand generated protocol: {0}".format(exc))
            data.pop("generator", None)
            data["protocol_status"] = "draft"
            note = (
                "Expanded editable copy created by Experiment Builder. "
                "The compact generator source is preserved at {0}."
            ).format(source_path)
            description = str(data.get("description", "")).strip()
            if note not in description:
                data["description"] = (description + "\n\n" + note).strip()

        draft = cls(
            data,
            file_path=None if expanded_from_generator else source_path,
            source_path=source_path,
            expanded_from_generator=expanded_from_generator,
        )
        return draft

    def validate(self):
        return ExperimentConfig.from_dict(
            copy.deepcopy(self.data),
            source_path=str(self.file_path or self.source_path or ""),
        )

    def save(self, path=None):
        target = Path(path).resolve() if path else self.file_path
        if target is None:
            raise BuilderError("Choose a JSON path before saving the experiment.")
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = target.with_suffix(target.suffix + ".tmp")
        payload = json.dumps(
            self.data,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
                output.write(payload)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            temporary_path.replace(target)
        except OSError as exc:
            try:
                temporary_path.unlink()
            except OSError:
                pass
            raise BuilderError("Cannot save experiment: {0}".format(exc))
        self.file_path = target
        self.source_path = target
        self.expanded_from_generator = False
        self.is_dirty = False
        return target

    def _touch(self, reset_validation=True):
        self.is_dirty = True
        if reset_validation and self.data.get("protocol_status") == "validated":
            self.data["protocol_status"] = "draft"

    def get_node(self, kind, path):
        if kind == "experiment":
            return self.data
        if kind == "block":
            return self.data["blocks"][path[0]]
        if kind == "trial":
            return self.data["blocks"][path[0]]["trials"][path[1]]
        if kind == "phase":
            return self.data["blocks"][path[0]]["trials"][path[1]]["phases"][
                path[2]
            ]
        raise BuilderError("Unknown tree node kind: {0}.".format(kind))

    def replace_node(self, kind, path, value):
        if not isinstance(value, dict):
            raise BuilderError("A tree node must be a JSON object.")
        if kind == "experiment":
            replacement = copy.deepcopy(value)
            previous_without_status = copy.deepcopy(self.data)
            replacement_without_status = copy.deepcopy(replacement)
            previous_status = previous_without_status.pop("protocol_status", None)
            replacement_status = replacement_without_status.pop(
                "protocol_status", None
            )
            if (
                previous_status == "validated"
                and replacement_status == "validated"
                and previous_without_status != replacement_without_status
            ):
                replacement["protocol_status"] = "draft"
            self.data = replacement
            self._touch(reset_validation=False)
            return
        if kind == "block":
            self.data["blocks"][path[0]] = copy.deepcopy(value)
        elif kind == "trial":
            self.data["blocks"][path[0]]["trials"][path[1]] = copy.deepcopy(value)
        elif kind == "phase":
            self.data["blocks"][path[0]]["trials"][path[1]]["phases"][
                path[2]
            ] = copy.deepcopy(value)
        else:
            raise BuilderError("Unknown tree node kind: {0}.".format(kind))
        self._touch()

    def _unique_id(self, base, existing):
        if base not in existing:
            return base
        suffix = 2
        while "{0}-{1}".format(base, suffix) in existing:
            suffix += 1
        return "{0}-{1}".format(base, suffix)

    def _block_ids(self):
        return {str(block.get("block_id", "")) for block in self.data["blocks"]}

    def _trial_ids(self):
        return {
            str(trial.get("trial_id", ""))
            for block in self.data["blocks"]
            for trial in block.get("trials", [])
        }

    def add_block(self):
        block_id = self._unique_id("block", self._block_ids())
        trial_id = self._unique_id("trial", self._trial_ids())
        block = {
            "block_id": block_id,
            "instructions": "Tekan SPASI untuk memulai blok.",
            "repetitions": 1,
            "randomize_trials": False,
            "trials": [self._new_trial(trial_id)],
        }
        self.data.setdefault("blocks", []).append(block)
        self._touch()
        return (len(self.data["blocks"]) - 1,)

    @staticmethod
    def _new_trial(trial_id):
        return {
            "trial_id": trial_id,
            "condition": "default",
            "correct_key": None,
            "metadata": {},
            "phases": [
                {
                    "name": "stimulus",
                    "duration_ms": 1000,
                    "text": "Stimulus",
                    "lights": [],
                    "collect_response": False,
                    "allowed_keys": [],
                }
            ],
        }

    def add_trial(self, block_index):
        trial_id = self._unique_id("trial", self._trial_ids())
        trials = self.data["blocks"][block_index].setdefault("trials", [])
        trials.append(self._new_trial(trial_id))
        self._touch()
        return (block_index, len(trials) - 1)

    def add_phase(self, block_index, trial_index):
        phases = self.data["blocks"][block_index]["trials"][trial_index].setdefault(
            "phases", []
        )
        phases.append(
            {
                "name": "phase-{0}".format(len(phases) + 1),
                "duration_ms": 1000,
                "text": "",
                "lights": [],
                "collect_response": False,
                "allowed_keys": [],
            }
        )
        self._touch()
        return (block_index, trial_index, len(phases) - 1)

    def duplicate(self, kind, path):
        if kind == "block":
            source = copy.deepcopy(self.get_node(kind, path))
            source["block_id"] = self._unique_id(
                str(source.get("block_id", "block")) + "-copy",
                self._block_ids(),
            )
            trial_ids = self._trial_ids()
            for trial in source.get("trials", []):
                trial["trial_id"] = self._unique_id(
                    str(trial.get("trial_id", "trial")) + "-copy",
                    trial_ids,
                )
                trial_ids.add(trial["trial_id"])
            insert_at = path[0] + 1
            self.data["blocks"].insert(insert_at, source)
            result = (insert_at,)
        elif kind == "trial":
            source = copy.deepcopy(self.get_node(kind, path))
            source["trial_id"] = self._unique_id(
                str(source.get("trial_id", "trial")) + "-copy",
                self._trial_ids(),
            )
            trials = self.data["blocks"][path[0]]["trials"]
            insert_at = path[1] + 1
            trials.insert(insert_at, source)
            result = (path[0], insert_at)
        elif kind == "phase":
            source = copy.deepcopy(self.get_node(kind, path))
            source["name"] = str(source.get("name", "phase")) + "-copy"
            phases = self.data["blocks"][path[0]]["trials"][path[1]]["phases"]
            insert_at = path[2] + 1
            phases.insert(insert_at, source)
            result = (path[0], path[1], insert_at)
        else:
            raise BuilderError("Select a block, trial, or phase to duplicate.")
        self._touch()
        return result

    def delete(self, kind, path):
        if kind == "block":
            del self.data["blocks"][path[0]]
            result = ("experiment", ())
        elif kind == "trial":
            del self.data["blocks"][path[0]]["trials"][path[1]]
            result = ("block", (path[0],))
        elif kind == "phase":
            del self.data["blocks"][path[0]]["trials"][path[1]]["phases"][path[2]]
            result = ("trial", (path[0], path[1]))
        else:
            raise BuilderError("The experiment root cannot be deleted.")
        self._touch()
        return result

    def move(self, kind, path, direction):
        if direction not in (-1, 1):
            raise BuilderError("Move direction must be -1 or 1.")
        if kind == "block":
            siblings = self.data["blocks"]
            index = path[0]
            prefix = ()
        elif kind == "trial":
            siblings = self.data["blocks"][path[0]]["trials"]
            index = path[1]
            prefix = (path[0],)
        elif kind == "phase":
            siblings = self.data["blocks"][path[0]]["trials"][path[1]]["phases"]
            index = path[2]
            prefix = (path[0], path[1])
        else:
            raise BuilderError("Select a block, trial, or phase to move.")
        destination = index + direction
        if destination < 0 or destination >= len(siblings):
            return path
        siblings[index], siblings[destination] = siblings[destination], siblings[index]
        self._touch()
        return prefix + (destination,)


class ExperimentBuilderPanel(tk.Frame):
    """Tree-based visual editor for experiment JSON configurations."""

    def __init__(self, master, use_experiment_callback=None, initial_path=None):
        tk.Frame.__init__(self, master, bg=BUILDER_COLORS["background"])
        self.use_experiment_callback = use_experiment_callback
        self.draft = ExperimentDraft.new()
        self.node_lookup = {}
        self.field_vars = {}
        self.text_fields = {}
        self.current_kind = "experiment"
        self.current_path = ()
        self._build()
        if initial_path:
            try:
                self.draft = ExperimentDraft.load(initial_path)
            except BuilderError:
                self.draft = ExperimentDraft.new()
        self.refresh_tree(select=("experiment", ()))
        self._refresh_document_status()

    def _build(self):
        toolbar = tk.Frame(self, bg=BUILDER_COLORS["surface"], padx=14, pady=10)
        toolbar.pack(fill="x")
        for label, command in (
            ("BARU", self.new_experiment),
            ("BUKA", self.open_experiment),
            ("SIMPAN", self.save_experiment),
            ("SIMPAN SEBAGAI", self.save_experiment_as),
            ("VALIDASI", self.validate_experiment),
            ("GUNAKAN DI EXECUTE", self.use_in_execute),
        ):
            tk.Button(
                toolbar,
                text=label,
                command=command,
                bg=(
                    BUILDER_COLORS["green"]
                    if label == "GUNAKAN DI EXECUTE"
                    else "#EEF3F8"
                ),
                fg=("#FFFFFF" if label == "GUNAKAN DI EXECUTE" else BUILDER_COLORS["navy"]),
                relief="flat",
                cursor="hand2",
                font=("Segoe UI Semibold", 9),
                padx=11,
                pady=7,
            ).pack(side="left", padx=(0, 7))

        self.document_status = tk.Label(
            toolbar,
            text="",
            bg=BUILDER_COLORS["surface"],
            fg=BUILDER_COLORS["muted"],
            font=("Segoe UI", 9),
        )
        self.document_status.pack(side="right")

        content = tk.PanedWindow(
            self,
            orient="horizontal",
            bg=BUILDER_COLORS["background"],
            sashwidth=6,
            relief="flat",
        )
        content.pack(fill="both", expand=True, padx=18, pady=14)

        tree_panel = tk.Frame(content, bg=BUILDER_COLORS["surface"], padx=12, pady=12)
        editor_panel = tk.Frame(
            content, bg=BUILDER_COLORS["surface"], padx=16, pady=12
        )
        content.add(tree_panel, minsize=340, width=420)
        content.add(editor_panel, minsize=460)

        tk.Label(
            tree_panel,
            text="STRUKTUR EKSPERIMEN",
            bg=BUILDER_COLORS["surface"],
            fg=BUILDER_COLORS["navy"],
            font=("Segoe UI Semibold", 12),
        ).pack(anchor="w", pady=(0, 9))
        tree_frame = tk.Frame(tree_panel, bg=BUILDER_COLORS["surface"])
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        tree_scroll = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._tree_selected)

        operations = tk.Frame(tree_panel, bg=BUILDER_COLORS["surface"])
        operations.pack(fill="x", pady=(10, 0))
        operation_groups = (
            (
                ("+ BLOK", self.add_block),
                ("+ TRIAL", self.add_trial),
                ("+ PHASE", self.add_phase),
            ),
            (
                ("DUPLIKASI", self.duplicate_selected),
                ("HAPUS", self.delete_selected),
                ("NAIK", lambda: self.move_selected(-1)),
                ("TURUN", lambda: self.move_selected(1)),
            ),
        )
        for row_index, operation_group in enumerate(operation_groups):
            operation_row = tk.Frame(
                operations, bg=BUILDER_COLORS["surface"]
            )
            operation_row.pack(fill="x", pady=(0, 4 if row_index == 0 else 0))
            for label, command in operation_group:
                tk.Button(
                    operation_row,
                    text=label,
                    command=command,
                    bg="#EEF3F8",
                    fg=(
                        BUILDER_COLORS["danger"]
                        if label == "HAPUS"
                        else BUILDER_COLORS["navy"]
                    ),
                    relief="flat",
                    cursor="hand2",
                    font=("Segoe UI Semibold", 8),
                    padx=7,
                    pady=5,
                ).pack(side="left", padx=(0, 4))

        self.editor_title = tk.Label(
            editor_panel,
            text="PROPERTI",
            bg=BUILDER_COLORS["surface"],
            fg=BUILDER_COLORS["navy"],
            font=("Segoe UI Semibold", 12),
        )
        self.editor_title.pack(anchor="w", pady=(0, 9))

        editor_canvas_frame = tk.Frame(editor_panel, bg=BUILDER_COLORS["surface"])
        editor_canvas_frame.pack(fill="both", expand=True)
        self.editor_canvas = tk.Canvas(
            editor_canvas_frame,
            bg=BUILDER_COLORS["surface"],
            highlightthickness=0,
        )
        editor_scroll = ttk.Scrollbar(
            editor_canvas_frame, orient="vertical", command=self.editor_canvas.yview
        )
        self.editor_canvas.configure(yscrollcommand=editor_scroll.set)
        self.editor_canvas.pack(side="left", fill="both", expand=True)
        editor_scroll.pack(side="right", fill="y")
        self.property_frame = tk.Frame(
            self.editor_canvas, bg=BUILDER_COLORS["surface"]
        )
        self.property_window = self.editor_canvas.create_window(
            (0, 0), window=self.property_frame, anchor="nw"
        )
        self.property_frame.bind("<Configure>", self._property_frame_resized)
        self.editor_canvas.bind("<Configure>", self._editor_canvas_resized)

        self.apply_button = tk.Button(
            editor_panel,
            text="TERAPKAN PROPERTI",
            command=self.apply_properties,
            bg=BUILDER_COLORS["navy"],
            fg="#FFFFFF",
            activebackground="#244C71",
            activeforeground="#FFFFFF",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 10),
            pady=9,
        )
        self.apply_button.pack(fill="x", pady=(10, 0))

    def _property_frame_resized(self, event):
        self.editor_canvas.configure(scrollregion=self.editor_canvas.bbox("all"))

    def _editor_canvas_resized(self, event):
        self.editor_canvas.itemconfigure(self.property_window, width=event.width)

    def _refresh_document_status(self, message=None, error=False):
        if message is None:
            path_text = str(self.draft.file_path) if self.draft.file_path else "belum disimpan"
            marker = " *" if self.draft.is_dirty else ""
            message = "{0}{1}".format(path_text, marker)
            if self.draft.expanded_from_generator:
                message += " | copy hasil ekspansi - Save As wajib"
        self.document_status.configure(
            text=message,
            fg=BUILDER_COLORS["danger"] if error else BUILDER_COLORS["muted"],
        )

    def refresh_tree(self, select=None):
        self.tree.delete(*self.tree.get_children())
        self.node_lookup = {}
        root_item = self.tree.insert(
            "",
            "end",
            text="Experiment: {0}".format(self.draft.data.get("title", "Untitled")),
            open=True,
        )
        self.node_lookup[root_item] = ("experiment", ())
        select_item = root_item if select == ("experiment", ()) else None
        for block_index, block in enumerate(self.draft.data.get("blocks", [])):
            block_path = (block_index,)
            block_item = self.tree.insert(
                root_item,
                "end",
                text="Block {0}: {1}".format(
                    block_index + 1, block.get("block_id", "<tanpa id>")
                ),
                open=True,
            )
            self.node_lookup[block_item] = ("block", block_path)
            if select == ("block", block_path):
                select_item = block_item
            for trial_index, trial in enumerate(block.get("trials", [])):
                trial_path = (block_index, trial_index)
                trial_item = self.tree.insert(
                    block_item,
                    "end",
                    text="Trial {0}: {1}".format(
                        trial_index + 1, trial.get("trial_id", "<tanpa id>")
                    ),
                    open=False,
                )
                self.node_lookup[trial_item] = ("trial", trial_path)
                if select == ("trial", trial_path):
                    select_item = trial_item
                for phase_index, phase in enumerate(trial.get("phases", [])):
                    phase_path = (block_index, trial_index, phase_index)
                    phase_item = self.tree.insert(
                        trial_item,
                        "end",
                        text="Phase {0}: {1}".format(
                            phase_index + 1, phase.get("name", "<tanpa nama>")
                        ),
                    )
                    self.node_lookup[phase_item] = ("phase", phase_path)
                    if select == ("phase", phase_path):
                        select_item = phase_item
        if select_item is None:
            select_item = root_item
        self.tree.selection_set(select_item)
        self.tree.focus(select_item)
        self.tree.see(select_item)
        self._show_properties(*self.node_lookup[select_item])
        self._refresh_document_status()

    def _tree_selected(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        kind_path = self.node_lookup.get(selected[0])
        if kind_path:
            self._show_properties(*kind_path)

    def _clear_property_form(self):
        for child in self.property_frame.winfo_children():
            child.destroy()
        self.field_vars = {}
        self.text_fields = {}

    def _label(self, text):
        tk.Label(
            self.property_frame,
            text=text,
            bg=BUILDER_COLORS["surface"],
            fg=BUILDER_COLORS["muted"],
            font=("Segoe UI Semibold", 9),
        ).pack(anchor="w", pady=(8, 3))

    def _entry(self, key, label, value, values=None):
        self._label(label)
        variable = tk.StringVar(value="" if value is None else str(value))
        self.field_vars[key] = variable
        if values:
            widget = ttk.Combobox(
                self.property_frame,
                textvariable=variable,
                values=values,
                state="readonly",
            )
        else:
            widget = tk.Entry(
                self.property_frame,
                textvariable=variable,
                relief="solid",
                bd=1,
                font=("Segoe UI", 10),
            )
        widget.pack(fill="x", ipady=5)

    def _text(self, key, label, value, height=4):
        self._label(label)
        widget = tk.Text(
            self.property_frame,
            height=height,
            wrap="word",
            relief="solid",
            bd=1,
            font=("Consolas", 9 if "json" in key else 10),
        )
        widget.insert("1.0", value or "")
        widget.pack(fill="x")
        self.text_fields[key] = widget

    def _check(self, key, label, value):
        variable = tk.BooleanVar(value=bool(value))
        self.field_vars[key] = variable
        tk.Checkbutton(
            self.property_frame,
            text=label,
            variable=variable,
            bg=BUILDER_COLORS["surface"],
            fg=BUILDER_COLORS["navy"],
            activebackground=BUILDER_COLORS["surface"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(8, 0))

    def _show_properties(self, kind, path):
        self.current_kind = kind
        self.current_path = path
        self._clear_property_form()
        node = self.draft.get_node(kind, path)
        self.editor_title.configure(
            text="PROPERTI {0}".format(kind.upper())
        )
        if kind == "experiment":
            self._entry("protocol_id", "Protocol ID", node.get("protocol_id", ""))
            self._entry("title", "Judul", node.get("title", ""))
            self._entry(
                "task_type",
                "Tipe tugas",
                node.get("task_type", "generic"),
                ("generic", "pebt"),
            )
            self._entry(
                "protocol_status",
                "Status protokol",
                node.get("protocol_status", "draft"),
                ("demo", "draft", "validated"),
            )
            self._text("description", "Deskripsi", node.get("description", ""), 4)
            self._text("instructions", "Instruksi fallback", node.get("instructions", ""), 4)
            self._entry("random_seed", "Random seed", node.get("random_seed", 0))
            self._entry(
                "data_directory",
                "Folder data",
                node.get("data_directory", "data/experiments"),
            )
            self._entry(
                "participant_conditions",
                "Kondisi partisipan (pisahkan dengan koma)",
                ", ".join(node.get("participant_conditions", [])),
            )
            display = node.get("display", {})
            self._check("display_fullscreen", "Fullscreen", display.get("fullscreen", True))
            self._entry(
                "display_background", "Warna background", display.get("background", "#000000")
            )
            self._entry(
                "display_foreground", "Warna teks", display.get("foreground", "#FFFFFF")
            )
            self._entry("display_font_size", "Ukuran font", display.get("font_size", 30))
            self._text(
                "instruction_pages_json",
                "Instruction pages (JSON array)",
                json.dumps(node.get("instruction_pages", []), ensure_ascii=False, indent=2),
                8,
            )
            self._text(
                "sources_json",
                "Sources (JSON array)",
                json.dumps(node.get("sources", []), ensure_ascii=False, indent=2),
                8,
            )
        elif kind == "block":
            self._entry("block_id", "Block ID", node.get("block_id", ""))
            self._text("instructions", "Instruksi block", node.get("instructions", ""), 5)
            self._entry("repetitions", "Repetitions", node.get("repetitions", 1))
            self._check(
                "randomize_trials",
                "Acak urutan trial",
                node.get("randomize_trials", False),
            )
        elif kind == "trial":
            self._entry("trial_id", "Trial ID", node.get("trial_id", ""))
            self._entry("condition", "Condition", node.get("condition", ""))
            self._entry("correct_key", "Correct key (opsional)", node.get("correct_key"))
            self._text(
                "metadata_json",
                "Metadata (JSON object)",
                json.dumps(node.get("metadata", {}), ensure_ascii=False, indent=2),
                10,
            )
        elif kind == "phase":
            self._entry("name", "Nama phase", node.get("name", ""))
            self._entry(
                "duration_ms",
                "Duration ms (kosong untuk response-gated)",
                node.get("duration_ms"),
            )
            self._text("text", "Teks stimulus", node.get("text", ""), 6)
            self._entry(
                "lights",
                "Lampu: left, right, front",
                ", ".join(node.get("lights", [])),
            )
            self._check(
                "collect_response",
                "Kumpulkan respons keyboard",
                node.get("collect_response", False),
            )
            self._entry(
                "allowed_keys",
                "Allowed keys (pisahkan dengan koma)",
                ", ".join(node.get("allowed_keys", [])),
            )
            self._check(
                "end_on_response",
                "Akhiri phase ketika respons diterima",
                node.get("end_on_response", False),
            )
            self._entry(
                "run_if_response_key",
                "Jalankan jika respons sebelumnya",
                node.get("run_if_response_key"),
            )
            self._entry("background", "Background override", node.get("background"))
            self._entry("foreground", "Foreground override", node.get("foreground"))
            self._entry("font_size", "Font size override", node.get("font_size"))

    def _field(self, key):
        return self.field_vars[key].get().strip()

    def _text_value(self, key):
        return self.text_fields[key].get("1.0", "end-1c")

    @staticmethod
    def _optional_int(value, label):
        value = value.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            raise BuilderError("{0} must be an integer or blank.".format(label))

    @staticmethod
    def _json_value(value, expected_type, label):
        try:
            parsed = json.loads(value or ("[]" if expected_type is list else "{}"))
        except json.JSONDecodeError as exc:
            raise BuilderError(
                "{0}: invalid JSON at line {1}, column {2}.".format(
                    label, exc.lineno, exc.colno
                )
            )
        if not isinstance(parsed, expected_type):
            raise BuilderError("{0} must be a JSON {1}.".format(label, expected_type.__name__))
        return parsed

    def apply_properties(self, show_message=True):
        node = copy.deepcopy(self.draft.get_node(self.current_kind, self.current_path))
        try:
            if self.current_kind == "experiment":
                node["schema_version"] = 1
                for key in (
                    "protocol_id",
                    "title",
                    "task_type",
                    "protocol_status",
                    "data_directory",
                ):
                    node[key] = self._field(key)
                node["description"] = self._text_value("description")
                node["instructions"] = self._text_value("instructions")
                node["random_seed"] = self._optional_int(
                    self._field("random_seed"), "Random seed"
                )
                node["participant_conditions"] = _split_csv(
                    self._field("participant_conditions")
                )
                node["display"] = {
                    "fullscreen": self.field_vars["display_fullscreen"].get(),
                    "background": self._field("display_background"),
                    "foreground": self._field("display_foreground"),
                    "font_size": self._optional_int(
                        self._field("display_font_size"), "Display font size"
                    ),
                }
                node["instruction_pages"] = self._json_value(
                    self._text_value("instruction_pages_json"),
                    list,
                    "Instruction pages",
                )
                node["sources"] = self._json_value(
                    self._text_value("sources_json"), list, "Sources"
                )
            elif self.current_kind == "block":
                node["block_id"] = self._field("block_id")
                node["instructions"] = self._text_value("instructions")
                node["repetitions"] = self._optional_int(
                    self._field("repetitions"), "Repetitions"
                )
                node["randomize_trials"] = self.field_vars[
                    "randomize_trials"
                ].get()
            elif self.current_kind == "trial":
                node["trial_id"] = self._field("trial_id")
                node["condition"] = self._field("condition")
                node["correct_key"] = self._field("correct_key") or None
                node["metadata"] = self._json_value(
                    self._text_value("metadata_json"), dict, "Metadata"
                )
            elif self.current_kind == "phase":
                node["name"] = self._field("name")
                node["duration_ms"] = self._optional_int(
                    self._field("duration_ms"), "Duration"
                )
                node["text"] = self._text_value("text")
                node["lights"] = _split_csv(self._field("lights"))
                node["collect_response"] = self.field_vars[
                    "collect_response"
                ].get()
                node["allowed_keys"] = _split_csv(self._field("allowed_keys"))
                node["end_on_response"] = self.field_vars[
                    "end_on_response"
                ].get()
                conditional_key = self._field("run_if_response_key")
                if conditional_key:
                    node["run_if_response_key"] = conditional_key.lower()
                else:
                    node.pop("run_if_response_key", None)
                for key in ("background", "foreground"):
                    value = self._field(key)
                    if value:
                        node[key] = value
                    else:
                        node.pop(key, None)
                font_size = self._optional_int(
                    self._field("font_size"), "Font size"
                )
                if font_size is None:
                    node.pop("font_size", None)
                else:
                    node["font_size"] = font_size
            self.draft.replace_node(self.current_kind, self.current_path, node)
        except BuilderError as exc:
            if show_message:
                messagebox.showerror("Properti Tidak Valid", str(exc), parent=self)
            return False
        selected = (self.current_kind, self.current_path)
        self.refresh_tree(select=selected)
        if show_message:
            self._refresh_document_status("Properti diterapkan; belum disimpan")
        return True

    def _confirm_discard(self):
        if not self.draft.is_dirty:
            return True
        return messagebox.askyesno(
            "Perubahan Belum Disimpan",
            "Buang perubahan yang belum disimpan?",
            parent=self,
        )

    def new_experiment(self):
        if not self._confirm_discard():
            return
        self.draft = ExperimentDraft.new()
        self.refresh_tree(select=("experiment", ()))

    def open_experiment(self):
        if not self._confirm_discard():
            return
        selected = filedialog.askopenfilename(
            parent=self,
            title="Buka eksperimen JSON",
            filetypes=(("JSON experiment", "*.json"), ("All files", "*.*")),
        )
        if not selected:
            return
        try:
            self.draft = ExperimentDraft.load(selected)
        except BuilderError as exc:
            messagebox.showerror("Eksperimen Tidak Dapat Dibuka", str(exc), parent=self)
            return
        self.refresh_tree(select=("experiment", ()))

    def save_experiment(self):
        if not self.apply_properties(show_message=False):
            return False
        if self.draft.file_path is None:
            return self.save_experiment_as()
        try:
            path = self.draft.save()
        except BuilderError as exc:
            messagebox.showerror("Gagal Menyimpan", str(exc), parent=self)
            return False
        self._refresh_document_status("Tersimpan: {0}".format(path))
        return True

    def save_experiment_as(self):
        if not self.apply_properties(show_message=False):
            return False
        initial_name = "{0}.json".format(
            self.draft.data.get("protocol_id", "experiment").lower()
        )
        selected = filedialog.asksaveasfilename(
            parent=self,
            title="Simpan eksperimen",
            defaultextension=".json",
            initialfile=initial_name,
            filetypes=(("JSON experiment", "*.json"),),
        )
        if not selected:
            return False
        try:
            path = self.draft.save(selected)
        except BuilderError as exc:
            messagebox.showerror("Gagal Menyimpan", str(exc), parent=self)
            return False
        self._refresh_document_status("Tersimpan: {0}".format(path))
        return True

    def validate_experiment(self, show_message=True):
        if not self.apply_properties(show_message=False):
            return None
        try:
            config = self.draft.validate()
        except (BuilderError, ConfigurationError) as exc:
            self._refresh_document_status("VALIDASI GAGAL: {0}".format(exc), error=True)
            if show_message:
                messagebox.showerror("Validasi Gagal", str(exc), parent=self)
            return None
        message = "VALID: {0} blok, {1} trial".format(
            len(config.blocks), config.trial_count
        )
        self._refresh_document_status(message)
        if show_message:
            messagebox.showinfo("Konfigurasi Valid", message, parent=self)
        return config

    def use_in_execute(self):
        if self.validate_experiment(show_message=True) is None:
            return
        if self.draft.is_dirty or self.draft.file_path is None:
            if not self.save_experiment():
                return
        if self.use_experiment_callback is not None:
            self.use_experiment_callback(str(self.draft.file_path))

    def _selected(self):
        return self.current_kind, self.current_path

    def add_block(self):
        path = self.draft.add_block()
        self.refresh_tree(select=("block", path))

    def add_trial(self):
        kind, path = self._selected()
        if kind == "experiment":
            messagebox.showinfo("Pilih Block", "Pilih block terlebih dahulu.", parent=self)
            return
        block_index = path[0]
        result = self.draft.add_trial(block_index)
        self.refresh_tree(select=("trial", result))

    def add_phase(self):
        kind, path = self._selected()
        if kind not in ("trial", "phase"):
            messagebox.showinfo("Pilih Trial", "Pilih trial terlebih dahulu.", parent=self)
            return
        result = self.draft.add_phase(path[0], path[1])
        self.refresh_tree(select=("phase", result))

    def duplicate_selected(self):
        kind, path = self._selected()
        try:
            result = self.draft.duplicate(kind, path)
        except BuilderError as exc:
            messagebox.showinfo("Tidak Dapat Duplikasi", str(exc), parent=self)
            return
        self.refresh_tree(select=(kind, result))

    def delete_selected(self):
        kind, path = self._selected()
        if kind == "experiment":
            messagebox.showinfo("Tidak Dapat Dihapus", "Root experiment tidak dapat dihapus.", parent=self)
            return
        if not messagebox.askyesno(
            "Hapus Item",
            "Hapus {0} terpilih?".format(kind),
            parent=self,
        ):
            return
        select = self.draft.delete(kind, path)
        self.refresh_tree(select=select)

    def move_selected(self, direction):
        kind, path = self._selected()
        try:
            result = self.draft.move(kind, path, direction)
        except BuilderError as exc:
            messagebox.showinfo("Tidak Dapat Dipindah", str(exc), parent=self)
            return
        self.refresh_tree(select=(kind, result))
