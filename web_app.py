"""Loopback-only Python backend and static server for the PEBT Web UI."""

from __future__ import absolute_import

import argparse
import json
import mimetypes
import os
import re
import secrets
import socket
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from experiment import ConfigurationError, ExperimentConfig
from experiment_document import DocumentError, ExperimentDocument
from relay_controller import (
    DemoRelayController,
    RelayController,
    RelayError,
    relay_states_for_sides,
)
from web_runtime import WebExperimentSession, WebSessionError


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"
CONFIG_ROOT = PROJECT_ROOT / "configs"
USER_CONFIG_ROOT = CONFIG_ROOT / "user"
DATA_ROOT = PROJECT_ROOT / "data" / "experiments"
MAX_REQUEST_BYTES = 5 * 1024 * 1024


class ApiError(RuntimeError):
    """Structured error returned by the local HTTP API."""

    def __init__(self, status, message, details=None):
        super(ApiError, self).__init__(message)
        self.status = int(status)
        self.message = str(message)
        self.details = details


def _json_boolean(mapping, field_name, default=False):
    """Return a JSON boolean without accepting truthy strings or numbers."""

    if field_name not in mapping:
        return default
    value = mapping[field_name]
    if not isinstance(value, bool):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "Field {0} wajib berupa boolean JSON.".format(field_name),
        )
    return value


def _inside(root, candidate):
    root_text = os.path.normcase(str(Path(root).resolve()))
    candidate_text = os.path.normcase(str(Path(candidate).resolve()))
    try:
        return os.path.commonpath((root_text, candidate_text)) == root_text
    except ValueError:
        return False


def _config_summary(config):
    minimum_ms, maximum_ms, response_gated = config.duration_bounds_ms
    phase_count = sum(
        block.repetitions
        * sum(len(trial.phases) for trial in block.trials)
        for block in config.blocks
    )
    return {
        "protocol_id": config.protocol_id,
        "title": config.title,
        "task_type": config.task_type,
        "protocol_status": config.protocol_status,
        "description": config.description,
        "block_count": len(config.blocks),
        "trial_count": config.trial_count,
        "phase_count": phase_count,
        "instruction_page_count": len(config.instruction_pages),
        "participant_conditions": list(config.participant_conditions),
        "source_count": len(config.sources),
        "random_seed": config.random_seed,
        "duration": {
            "minimum_ms": minimum_ms,
            "maximum_ms": maximum_ms,
            "response_gated": response_gated,
        },
        "config_sha256": config.config_sha256,
    }


class LocalWebApplication(object):
    """Own configuration storage, the relay, and at most one session."""

    def __init__(
        self,
        controller=None,
        demo_mode=False,
        data_root=None,
        user_config_root=None,
    ):
        self.demo_mode = bool(demo_mode)
        self.controller = controller or (
            DemoRelayController() if self.demo_mode else RelayController()
        )
        self.control_token = secrets.token_urlsafe(32)
        self.relay_lock = threading.RLock()
        self.session_lock = threading.RLock()
        self.config_lock = threading.RLock()
        self.session = None
        self.data_root = Path(data_root or DATA_ROOT).resolve()
        self.user_config_root = Path(user_config_root or USER_CONFIG_ROOT).resolve()
        self.user_config_root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)

    def _active_session(self):
        return self.session is not None and self.session.is_active

    def _session_for_client(self, session_id, client_id):
        requested_session_id = str(session_id or "").strip()
        requested_client_id = str(client_id or "").strip()
        with self.session_lock:
            session = self.session
            if session is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "Belum ada sesi eksperimen.")
            current_session_id = session.snapshot()["session_id"]
            if (
                not requested_session_id
                or not secrets.compare_digest(
                    requested_session_id,
                    current_session_id,
                )
            ):
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Aksi berasal dari sesi eksperimen yang sudah kedaluwarsa.",
                )
            if (
                not requested_client_id
                or not secrets.compare_digest(
                    requested_client_id,
                    session.client_id,
                )
            ):
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Sesi eksperimen dikendalikan oleh tab browser lain.",
                )
            return session

    def _ensure_manual_available(self):
        if self._active_session():
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Relay sedang dikunci oleh eksperimen aktif.",
            )

    def _resolve_config(self, config_id):
        value = str(config_id or "").strip().replace("\\", "/")
        if not value:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Config ID wajib diisi.")
        candidate = (
            (PROJECT_ROOT / value).resolve()
            if not Path(value).is_absolute()
            else Path(value).resolve()
        )
        if not _inside(CONFIG_ROOT, candidate) or candidate.suffix.lower() != ".json":
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "Konfigurasi harus berupa file JSON di dalam folder configs.",
            )
        if not candidate.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "Konfigurasi tidak ditemukan.")
        return candidate

    def _config_id(self, path):
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            if _inside(self.user_config_root, resolved):
                return "configs/user/{0}".format(resolved.name)
            raise

    def list_configs(self):
        items = []
        for path in sorted(CONFIG_ROOT.rglob("*.json")):
            try:
                config = ExperimentConfig.load(path)
                item = _config_summary(config)
                item.update({"id": self._config_id(path), "valid": True})
            except ConfigurationError as exc:
                item = {
                    "id": self._config_id(path),
                    "title": path.stem,
                    "protocol_id": path.stem,
                    "protocol_status": "invalid",
                    "valid": False,
                    "error": str(exc),
                }
            items.append(item)
        return items

    def load_config(self, config_id, builder=False):
        path = self._resolve_config(config_id)
        if builder:
            try:
                draft = ExperimentDocument.load(path)
                config = draft.validate()
            except (DocumentError, ConfigurationError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, str(exc))
            return {
                "id": None if draft.expanded_from_generator else self._config_id(path),
                "source_id": self._config_id(path),
                "expanded_from_generator": draft.expanded_from_generator,
                "document": draft.data,
                "summary": _config_summary(config),
            }
        try:
            raw_data = json.loads(path.read_text(encoding="utf-8"))
            config = ExperimentConfig.load(path)
        except (OSError, json.JSONDecodeError, ConfigurationError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc))
        return {
            "id": self._config_id(path),
            "source_id": self._config_id(path),
            "expanded_from_generator": False,
            "document": raw_data,
            "summary": _config_summary(config),
        }

    def validate_config(self, document):
        if not isinstance(document, dict):
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "Document konfigurasi wajib berupa JSON object.",
            )
        try:
            config = ExperimentConfig.from_dict(document, source_path="web-builder")
        except ConfigurationError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc))
        return _config_summary(config)

    def save_config(self, document, filename, overwrite=False):
        if not isinstance(overwrite, bool):
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "Field overwrite wajib berupa boolean JSON.",
            )
        summary = self.validate_config(document)
        raw_name = str(filename or "").strip()
        if not raw_name:
            protocol_id = str(document.get("protocol_id", "experiment"))
            raw_name = protocol_id.lower() + ".json"
        if not raw_name.lower().endswith(".json"):
            raw_name += ".json"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(raw_name).name)
        safe_name = safe_name.strip(".-") or "experiment.json"
        if not safe_name.lower().endswith(".json"):
            safe_name += ".json"
        target = (self.user_config_root / safe_name).resolve()
        if not _inside(self.user_config_root, target):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Nama file tidak valid.")
        with self.config_lock:
            if target.exists() and not overwrite:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "File sudah ada. Aktifkan overwrite untuk menggantinya.",
                )
            try:
                path = ExperimentDocument(document).save(target)
            except DocumentError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, str(exc))
        return {
            "id": self._config_id(path),
            "filename": path.name,
            "summary": summary,
        }

    def relay_snapshot(self):
        active_session = self._active_session()
        connected = bool(self.controller.is_connected)
        payload = {
            "mode": "demo" if self.demo_mode else "hardware",
            "connected": connected,
            "device_id": self.controller.device_id,
            "states": [0, 0, 0, 0] if not connected else None,
            "leased_by_experiment": active_session,
            "error": None,
        }
        if active_session and self.session is not None:
            session_state = self.session.snapshot()
            relay_state = session_state.get("relay_state")
            payload["states"] = (
                None if relay_state is None else list(relay_state)
            )
            if relay_state is None:
                payload["error"] = (
                    session_state.get("error")
                    or "Status relay eksperimen tidak dapat diverifikasi."
                )
        elif connected:
            try:
                with self.relay_lock:
                    payload["states"] = list(self.controller.get_states())
            except RelayError as exc:
                payload["error"] = str(exc)
        return payload

    def connect_relay(self):
        with self.session_lock:
            self._ensure_manual_available()
            try:
                with self.relay_lock:
                    device_id = self.controller.connect()
                    states = tuple(self.controller.get_states())
            except RelayError as exc:
                raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        return {"device_id": device_id, "states": list(states)}

    def apply_manual(self, sides):
        with self.session_lock:
            self._ensure_manual_available()
            states = relay_states_for_sides(
                left=_json_boolean(sides, "left"),
                right=_json_boolean(sides, "right"),
                front=_json_boolean(sides, "front"),
            )
            if not self.controller.is_connected:
                raise ApiError(HTTPStatus.CONFLICT, "Hubungkan relay terlebih dahulu.")
            try:
                with self.relay_lock:
                    self.controller.set_states(states)
                    actual = tuple(self.controller.get_states())
            except RelayError as exc:
                raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        if actual != states:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "Relay readback tidak sesuai dengan state yang diminta.",
                {"requested": list(states), "actual": list(actual)},
            )
        return {"requested": list(states), "actual": list(actual)}

    def _all_off_unchecked(self):
        if not self.controller.is_connected:
            return {"states": [0, 0, 0, 0], "connected": False}
        try:
            with self.relay_lock:
                self.controller.set_states((0, 0, 0, 0))
                actual = tuple(self.controller.get_states())
        except RelayError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        if actual != (0, 0, 0, 0):
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "Readback menunjukkan relay belum OFF.",
                {"actual": list(actual)},
            )
        return {"states": list(actual), "connected": True}

    def all_off(self, allow_during_session=False):
        if allow_during_session:
            return self._all_off_unchecked()
        with self.session_lock:
            self._ensure_manual_available()
            return self._all_off_unchecked()

    def disconnect_relay(self):
        with self.session_lock:
            self._ensure_manual_available()
            if not self.controller.is_connected:
                return self.relay_snapshot()
            self.all_off()
            try:
                with self.relay_lock:
                    self.controller.close()
            except RelayError as exc:
                raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        return self.relay_snapshot()

    def experiment_snapshot(
        self,
        after_version=None,
        timeout_seconds=0.0,
        session_id=None,
        client_id=None,
    ):
        if after_version is not None:
            session = self._session_for_client(session_id, client_id)
            return session.wait_for_snapshot(
                after_version,
                timeout_seconds=timeout_seconds,
            )
        with self.session_lock:
            session = self.session
        if session is None:
            return {
                "status": "idle",
                "screen": "idle",
                "waiting_for": None,
                "gate_token": None,
                "version": 0,
            }
        return session.snapshot()

    def start_experiment(self, payload):
        participant_id = str(payload.get("participant_id", "")).strip()
        if not participant_id:
            raise ApiError(HTTPStatus.BAD_REQUEST, "ID partisipan wajib diisi.")
        client_id = str(payload.get("client_id", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", client_id):
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "Client ID tab browser tidak valid.",
            )
        allow_unvalidated = _json_boolean(payload, "allow_unvalidated")
        session_label = str(payload.get("session_label", "")).strip()
        participant_condition = str(
            payload.get("participant_condition", "")
        ).strip().lower()
        document = payload.get("document")
        config_id = payload.get("config_id")
        try:
            if document is not None:
                if not isinstance(document, dict):
                    raise ApiError(
                        HTTPStatus.BAD_REQUEST,
                        "Document konfigurasi wajib berupa JSON object.",
                    )
                config = ExperimentConfig.from_dict(
                    document,
                    source_path="web-builder",
                )
            elif config_id:
                config = ExperimentConfig.load(self._resolve_config(config_id))
            else:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "Pilih atau kirim konfigurasi eksperimen.",
                )
        except ConfigurationError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc))

        if (
            config.protocol_status != "validated"
            and not allow_unvalidated
        ):
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Protokol belum berstatus validated. Konfirmasi mode draft/demo diperlukan.",
                {"protocol_status": config.protocol_status},
            )

        with self.session_lock:
            if self._active_session():
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Selesaikan atau batalkan eksperimen yang sedang aktif.",
                )
            if not self.controller.is_connected:
                try:
                    with self.relay_lock:
                        self.controller.connect()
                except RelayError as exc:
                    raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
            try:
                self.session = WebExperimentSession(
                    config=config,
                    participant_id=participant_id,
                    session_label=session_label,
                    participant_condition=participant_condition,
                    controller=self.controller,
                    relay_lock=self.relay_lock,
                    output_directory=self.data_root,
                    client_id=client_id,
                )
            except (ConfigurationError, ValueError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, str(exc))
            return self.session.start()

    def experiment_action(self, payload):
        session = self._session_for_client(
            payload.get("session_id"),
            payload.get("client_id"),
        )
        try:
            return session.submit_action(
                payload.get("action"),
                key=payload.get("key"),
                client_elapsed_ms=payload.get("client_elapsed_ms"),
                gate_token=payload.get("gate_token"),
            )
        except WebSessionError as exc:
            raise ApiError(HTTPStatus.CONFLICT, str(exc))

    def heartbeat(self, payload):
        session = self._session_for_client(
            payload.get("session_id"),
            payload.get("client_id"),
        )
        session.heartbeat()
        return session.snapshot()

    def dismiss_experiment(self, payload):
        with self.session_lock:
            if self.session is None:
                return self.experiment_snapshot()
            session = self._session_for_client(
                payload.get("session_id"),
                payload.get("client_id"),
            )
            if session.is_active:
                raise ApiError(
                    HTTPStatus.CONFLICT,
                    "Eksperimen aktif tidak dapat ditutup dari dashboard.",
                )
            if self.session is session:
                self.session = None
        return self.experiment_snapshot()

    def list_results(self, limit=12):
        paths = sorted(
            self.data_root.glob("*.summary.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:limit]
        results = []
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            results.append(
                {
                    "filename": path.name,
                    "status": data.get("status"),
                    "started_at_utc": data.get("started_at_utc"),
                    "participant_id": data.get("participant_id"),
                    "protocol": data.get("protocol", {}),
                    "metrics": data.get("metrics", {}),
                }
            )
        return results

    def system_payload(self, client_id=None):
        with self.session_lock:
            session = self.session
        if session is None:
            experiment_owner = None
        elif client_id and secrets.compare_digest(
            str(client_id),
            session.client_id,
        ):
            experiment_owner = "this_client"
        else:
            experiment_owner = "other_client"
        return {
            "application": "PEBT UGM Experiment Studio",
            "version": "2.0-web",
            "mode": "demo" if self.demo_mode else "hardware",
            "python": sys.version.split()[0],
            "control_token": self.control_token,
            "relay": self.relay_snapshot(),
            "experiment": self.experiment_snapshot(),
            "experiment_owner": experiment_owner,
            "config_count": len(self.list_configs()),
        }

    def shutdown(self):
        errors = []
        if self.session is not None and self.session.is_active:
            self.session.request_abort(wait=True, timeout=3.0)
        try:
            self.all_off(allow_during_session=True)
        except ApiError as exc:
            errors.append("FAIL-SAFE OFF GAGAL: {0}".format(exc.message))
        if self.controller.is_connected:
            try:
                with self.relay_lock:
                    self.controller.close()
            except RelayError as exc:
                errors.append("PENUTUPAN RELAY GAGAL: {0}".format(exc))
        for message in errors:
            sys.stderr.write("[SAFETY ERROR] {0}\n".format(message))
        return errors


class PebtRequestHandler(BaseHTTPRequestHandler):
    """Serve the local SPA and its JSON API."""

    server_version = "PEBTLocalWeb/2.0"

    @property
    def application(self):
        return self.server.application

    def log_message(self, format_string, *args):
        # Runtime polling is expected several times per second. Keep the
        # operator console useful while still logging state-changing requests.
        if self.command == "GET" and urlsplit(self.path).path in (
            "/api/experiment",
            "/api/relay",
            "/api/results",
        ):
            return
        sys.stderr.write(
            "[%s] %s\n" % (self.log_date_time_string(), format_string % args)
        )

    def _host_allowed(self):
        try:
            host = urlsplit("//" + self.headers.get("Host", "")).hostname
        except ValueError:
            return False
        return str(host or "").lower() in ("127.0.0.1", "localhost", "::1")

    def _request_source_allowed(self):
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        return (
            parsed.scheme == "http"
            and str(parsed.hostname or "").lower()
            in ("127.0.0.1", "localhost", "::1")
        )

    def _send_headers(self, status, content_type, length):
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()

    def _json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _api_ok(self, data=None, status=HTTPStatus.OK):
        self._json({"ok": True, "data": data}, status=status)

    def _api_error(self, error):
        payload = {
            "ok": False,
            "error": {
                "message": error.message,
                "details": error.details,
                "status": error.status,
            },
        }
        self._json(payload, status=error.status)

    def _require_control_token(self):
        provided = self.headers.get("X-PEBT-Token", "")
        if not secrets.compare_digest(provided, self.application.control_token):
            raise ApiError(HTTPStatus.FORBIDDEN, "Control token tidak valid.")

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Content-Length tidak valid.")
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "Request JSON kosong atau melebihi batas ukuran.",
            )
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type != "application/json":
            raise ApiError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "API hanya menerima application/json.",
            )
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON tidak valid: {0}".format(exc))

    def _serve_static(self, request_path):
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (WEB_ROOT / relative).resolve()
        if not _inside(WEB_ROOT, candidate) or not candidate.is_file():
            candidate = WEB_ROOT / "index.html"
        try:
            body = candidate.read_bytes()
        except OSError:
            raise ApiError(HTTPStatus.NOT_FOUND, "Web UI asset tidak ditemukan.")
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "application/json",
        ):
            content_type += "; charset=utf-8"
        self._send_headers(HTTPStatus.OK, content_type, len(body))
        self.wfile.write(body)

    def do_GET(self):
        try:
            if not self._host_allowed():
                raise ApiError(HTTPStatus.FORBIDDEN, "Host tidak diizinkan.")
            if not self._request_source_allowed():
                raise ApiError(HTTPStatus.FORBIDDEN, "Origin request tidak diizinkan.")
            parsed = urlsplit(self.path)
            if not parsed.path.startswith("/api/"):
                self._serve_static(parsed.path)
                return
            query = parse_qs(parsed.query)
            if parsed.path == "/api/system":
                client_id = (query.get("client_id") or [None])[0]
                self._api_ok(self.application.system_payload(client_id=client_id))
            elif parsed.path == "/api/configs":
                self._api_ok(self.application.list_configs())
            elif parsed.path == "/api/config":
                config_id = (query.get("id") or [""])[0]
                builder = (query.get("mode") or [""])[0] == "builder"
                self._api_ok(self.application.load_config(config_id, builder=builder))
            elif parsed.path == "/api/relay":
                self._api_ok(self.application.relay_snapshot())
            elif parsed.path == "/api/experiment":
                after_value = (query.get("after") or [None])[0]
                timeout_value = (query.get("timeout_ms") or ["0"])[0]
                if after_value is None:
                    self._api_ok(self.application.experiment_snapshot())
                else:
                    try:
                        after_version = int(after_value)
                        timeout_ms = max(0, min(15000, int(timeout_value)))
                    except (TypeError, ValueError):
                        raise ApiError(
                            HTTPStatus.BAD_REQUEST,
                            "Parameter long-poll experiment tidak valid.",
                        )
                    self._api_ok(
                        self.application.experiment_snapshot(
                            after_version=after_version,
                            timeout_seconds=timeout_ms / 1000.0,
                            session_id=(query.get("session_id") or [None])[0],
                            client_id=(query.get("client_id") or [None])[0],
                        )
                    )
            elif parsed.path == "/api/results":
                self._api_ok(self.application.list_results())
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint tidak ditemukan.")
        except ApiError as exc:
            self._api_error(exc)
        except Exception as exc:
            self._api_error(ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc)))

    def do_POST(self):
        try:
            if not self._host_allowed():
                raise ApiError(HTTPStatus.FORBIDDEN, "Host tidak diizinkan.")
            if not self._request_source_allowed():
                raise ApiError(HTTPStatus.FORBIDDEN, "Origin request tidak diizinkan.")
            self._require_control_token()
            parsed = urlsplit(self.path)
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "Body harus berupa JSON object.")
            if parsed.path == "/api/config/validate":
                data = self.application.validate_config(payload.get("document"))
            elif parsed.path == "/api/config/save":
                document = payload.get("document")
                if not isinstance(document, dict):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "Document wajib berupa object.")
                data = self.application.save_config(
                    document,
                    payload.get("filename"),
                    overwrite=_json_boolean(payload, "overwrite"),
                )
            elif parsed.path == "/api/relay/connect":
                data = self.application.connect_relay()
            elif parsed.path == "/api/relay/apply":
                sides = payload.get("sides")
                if not isinstance(sides, dict):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "sides wajib berupa object.")
                data = self.application.apply_manual(sides)
            elif parsed.path == "/api/relay/off":
                data = self.application.all_off()
            elif parsed.path == "/api/relay/disconnect":
                data = self.application.disconnect_relay()
            elif parsed.path == "/api/experiment/start":
                data = self.application.start_experiment(payload)
            elif parsed.path == "/api/experiment/action":
                data = self.application.experiment_action(payload)
            elif parsed.path == "/api/experiment/heartbeat":
                data = self.application.heartbeat(payload)
            elif parsed.path == "/api/experiment/dismiss":
                data = self.application.dismiss_experiment(payload)
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "Endpoint tidak ditemukan.")
            self._api_ok(data)
        except ApiError as exc:
            self._api_error(exc)
        except Exception as exc:
            self._api_error(ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc)))


class _ThreadingHTTPServerV6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def create_server(application, host="127.0.0.1", port=8765):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("The local Web UI may only bind to a loopback address.")
    server_type = _ThreadingHTTPServerV6 if host == "::1" else ThreadingHTTPServer
    server = server_type((host, int(port)), PebtRequestHandler)
    server.daemon_threads = True
    server.application = application
    return server


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="PEBT UGM local Web UI with a Python experiment backend."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use the in-memory relay; no Ydci.dll or hardware required.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Loopback bind address.")
    parser.add_argument("--port", type=int, default=8765, help="Local HTTP port.")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening the default browser.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    application = LocalWebApplication(demo_mode=args.demo)
    server = create_server(application, host=args.host, port=args.port)
    actual_host, actual_port = server.server_address[:2]
    browser_host = "127.0.0.1" if actual_host == "0.0.0.0" else actual_host
    if ":" in browser_host and not browser_host.startswith("["):
        browser_host = "[{0}]".format(browser_host)
    url = "http://{0}:{1}/".format(browser_host, actual_port)
    print("PEBT UGM Web UI: {0}".format(url))
    print("Mode: {0}".format("DEMO" if args.demo else "HARDWARE"))
    print(
        "Tekan Ctrl+C untuk menghentikan server; backend akan meminta "
        "dan memverifikasi seluruh output relay OFF."
    )
    if not args.no_browser:
        webbrowser.open(url)
    shutdown_errors = []
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nMenghentikan server…")
    finally:
        server.shutdown()
        server.server_close()
        shutdown_errors = application.shutdown()
    return 1 if shutdown_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
