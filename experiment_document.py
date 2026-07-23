"""Toolkit-independent experiment document storage for the Web UI backend."""

from __future__ import absolute_import

import copy
import json
import os
import tempfile
from pathlib import Path

from experiment import ConfigurationError, ExperimentConfig
from pebt import PEBTGeneratorError, expand_pebt_configuration


class DocumentError(ValueError):
    """Raised when an experiment document cannot be loaded or saved."""


class ExperimentDocument(object):
    """Editable JSON document with expansion, validation, and atomic save."""

    def __init__(self, data, source_path=None, expanded_from_generator=False):
        if not isinstance(data, dict):
            raise DocumentError("Experiment document must be a JSON object.")
        self.data = copy.deepcopy(data)
        self.source_path = Path(source_path).resolve() if source_path else None
        self.expanded_from_generator = bool(expanded_from_generator)

    @classmethod
    def load(cls, path, expand_generator=True):
        source_path = Path(path).resolve()
        try:
            source_bytes = source_path.read_bytes()
            data = json.loads(source_bytes.decode("utf-8"))
        except OSError as exc:
            raise DocumentError("Cannot open experiment: {0}".format(exc))
        except UnicodeDecodeError as exc:
            raise DocumentError("Experiment must be UTF-8: {0}".format(exc))
        except json.JSONDecodeError as exc:
            raise DocumentError(
                "Invalid JSON at line {0}, column {1}: {2}".format(
                    exc.lineno, exc.colno, exc.msg
                )
            )
        if not isinstance(data, dict):
            raise DocumentError("Experiment document must be a JSON object.")
        expanded = bool(expand_generator and data.get("generator") is not None)
        if expanded:
            try:
                data = expand_pebt_configuration(data)
            except PEBTGeneratorError as exc:
                raise DocumentError(
                    "Cannot expand generated protocol: {0}".format(exc)
                )
            data.pop("generator", None)
            data["protocol_status"] = "draft"
            description = str(data.get("description", "")).strip()
            note = (
                "Expanded editable copy created by the local Web UI. "
                "The compact generator source remains unchanged."
            )
            if note not in description:
                data["description"] = (description + "\n\n" + note).strip()
        return cls(
            data,
            source_path=source_path,
            expanded_from_generator=expanded,
        )

    def validate(self, source_path=None):
        try:
            return ExperimentConfig.from_dict(
                copy.deepcopy(self.data),
                source_path=str(source_path or self.source_path or "web-builder"),
            )
        except ConfigurationError:
            raise

    def save(self, path):
        target = Path(path).resolve()
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=str(target.parent),
                prefix=target.name + ".",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                output.write(payload)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(target)
        except OSError as exc:
            try:
                if temporary is not None:
                    temporary.unlink()
            except OSError:
                pass
            raise DocumentError("Cannot save experiment: {0}".format(exc))
        self.source_path = target
        self.expanded_from_generator = False
        return target
